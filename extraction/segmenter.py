# -*- coding: utf-8 -*-
"""Structure-aware report text segmentation."""

import re
import os
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from docx import Document


@dataclass
class TextSegment:
    """A text segment with document position and section metadata."""
    segment_id: str                           # Unique identifier
    section_title: str                        # Containing section title
    section_path: List[str] = field(default_factory=list)  # Section path, for example ['1', '1.1', '1.1.1']
    content: str = ""                         # Text content
    page_number: int = 0                      # Approximate page number
    segment_type: str = "text"                # text / table / figure
    parent_section: str = ""                  # Parent section title
    metadata: dict = field(default_factory=dict)  # Additional metadata


class StructureAwareSegmenter:
    """Segment DOCX text using structure, paragraph fallback and length limits."""

    # Heading patterns for numbered and Chinese chapter/section headings
    SECTION_PATTERNS = [
        re.compile(r'^第[一二三四五六七八九十百千]+章'),           # Chinese chapter heading
        re.compile(r'^第[一二三四五六七八九十百千]+节'),           # Chinese section heading
        re.compile(r'^\d+(\.\d+)*\s'),                         # Numbered headings such as 1., 1.1 or 1.1.1
        re.compile(r'^[一二三四五六七八九十]、'),                  # Chinese numeral followed by an enumeration comma
        re.compile(r'^（[一二三四五六七八九十]）'),                # Parenthesized Chinese numeral
        re.compile(r'^\d+[、．.]'),                              # 1、
    ]

    # Common section keywords in geological investigation reports
    SECTION_KEYWORDS = [
        '前言', '概述', '绪论', '引言',
        '工程地质', '水文地质', '地形地貌', '地层岩性', '地质构造',
        '滑坡特征', '滑坡体', '变形特征', '破坏机制', '稳定性',
        '监测', '预警', '防治', '治理', '结论', '建议', '参考文献',
        '自然地理', '气象', '水文', '地震', '人类工程活动',
        '勘查', '钻探', '物探', '试验', '计算',
        '滑坡', '灾害', '隐患', '裂缝', '塌陷', '泥石流',
    ]

    def __init__(self, docx_path: str, max_segment_len: int = 1500, overlap: int = 150):
        self.docx_path = docx_path
        self.doc = Document(docx_path)
        self.segments: List[TextSegment] = []
        self._section_counters: Dict[int, int] = {}  # level → counter
        self.max_segment_len = max_segment_len        # Maximum characters per segment
        self.overlap = overlap                        # Overlap characters between segments

    # Main workflow

    def segment(self) -> List[TextSegment]:
        """Run document segmentation."""
        print(f"📖 开始结构感知分段: {os.path.basename(self.docx_path)}")
        print(f"   文档段落数: {len(self.doc.paragraphs)}")
        print(f"   文档表格数: {len(self.doc.tables)}")

        self._extract_segments()

        print(f"  ✅ 分段完成: {len(self.segments)} 个文本段")
        return self.segments

    # Segment extraction

    def _extract_segments(self):
        """Extract segments from document paragraphs."""
        current_section = {'title': '文档开头', 'path': [], 'level': 0}
        current_content = []
        segment_idx = 0
        raw_paragraphs = []  # Collect all paragraphs for fallback segmentation.

        for para in self.doc.paragraphs:
            text = para.text.strip()
            if not text:
                # Treat an empty line as a paragraph separator.
                if current_content:
                    self._flush_segment(
                        current_section, current_content, segment_idx
                    )
                    segment_idx += 1
                    current_content = []
                continue

            raw_paragraphs.append(text)

            # Detect section headings.
            section_match = self._detect_section_heading(text, para)
            if section_match:
                # Save the preceding content.
                if current_content:
                    self._flush_segment(
                        current_section, current_content, segment_idx
                    )
                    segment_idx += 1
                    current_content = []

                # Update current section information.
                current_section = section_match
                # Retain the heading itself as a segment.
                self._flush_segment(
                    current_section, [text], segment_idx
                )
                segment_idx += 1
                continue

            current_content.append(text)

        # Process the final segment.
        if current_content:
            self._flush_segment(current_section, current_content, segment_idx)

        # Fallback: when only one segment exists, resegment using paragraphs and a sliding window.
        if len(self.segments) <= 1 and raw_paragraphs:
            self.segments = []
            self._paragraph_based_segment(raw_paragraphs)

        # Postprocessing: merge very short adjacent segments.
        self._merge_short_segments()

        # Postprocessing: split overlong segments.
        self._split_long_segments()

    def _paragraph_based_segment(self, paragraphs: List[str]):
        """Use paragraph-level fallback when no useful heading structure is available."""
        if not paragraphs:
            return

        # Total text length
        full_text = '\n\n'.join(paragraphs)
        
        # Keep one or two short paragraphs as a single segment.
        if len(paragraphs) <= 2 and len(full_text) <= self.max_segment_len:
            segment = TextSegment(
                segment_id="seg_0000",
                section_title="全文",
                section_path=[],
                content=full_text,
                page_number=0,
                segment_type="text",
                parent_section="",
            )
            self.segments.append(segment)
            return

        # Group about 2-3 paragraphs, targeting roughly 500-800 characters per group.
        target_chunk = min(self.max_segment_len, 800)
        segments_out = []
        current_paras = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para)
            
            if current_len + para_len > target_chunk and current_paras and len(current_paras) >= 2:
                # Flush the current group when full.
                seg_text = '\n\n'.join(current_paras)
                segments_out.append(seg_text)
                
                # Sliding window: retain the final paragraph as overlapping context.
                if self.overlap > 0 and len(current_paras) >= 1:
                    overlap_para = current_paras[-1]
                    current_paras = [overlap_para]
                    current_len = len(overlap_para)
                else:
                    current_paras = []
                    current_len = 0
            
            current_paras.append(para)
            current_len += para_len
        
        # Process the final segment.
        if current_paras:
            seg_text = '\n\n'.join(current_paras)
            segments_out.append(seg_text)

        # Create a TextSegment object.
        for idx, seg_text in enumerate(segments_out):
            segment = TextSegment(
                segment_id=f"seg_{idx:04d}",
                section_title=f"第{idx + 1}段",
                section_path=[],
                content=seg_text,
                page_number=0,
                segment_type="text",
                parent_section="",
            )
            self.segments.append(segment)

    def _merge_short_segments(self):
        """Merge adjacent segments shorter than 50 characters where applicable."""
        if len(self.segments) <= 1:
            return

        MIN_SEGMENT_LEN = 50
        merged = []
        buffer = self.segments[0]

        for seg in self.segments[1:]:
            if len(buffer.content) < MIN_SEGMENT_LEN or len(seg.content) < MIN_SEGMENT_LEN:
                # Merge adjacent short segments.
                merged_content = buffer.content + '\n' + seg.content
                buffer = TextSegment(
                    segment_id=buffer.segment_id,
                    section_title=buffer.section_title or seg.section_title or "全文",
                    section_path=buffer.section_path,
                    content=merged_content,
                    page_number=buffer.page_number,
                    segment_type=buffer.segment_type,
                    parent_section=buffer.parent_section,
                    metadata=dict(buffer.metadata),
                )
            else:
                # Keep both segments when each is sufficiently long.
                if len(buffer.content) >= MIN_SEGMENT_LEN:
                    merged.append(buffer)
                else:
                    # Append the next segment when the buffer remains too short.
                    seg_content = buffer.content + '\n' + seg.content
                    buffer = TextSegment(
                        segment_id=seg.segment_id,
                        section_title=seg.section_title,
                        section_path=seg.section_path,
                        content=seg_content,
                        page_number=seg.page_number,
                        segment_type=seg.segment_type,
                        parent_section=seg.parent_section,
                        metadata=dict(seg.metadata),
                    )
                    continue
                buffer = seg

        if len(buffer.content) >= MIN_SEGMENT_LEN:
            merged.append(buffer)
        elif merged:
            # Merge a very short final segment into the preceding one.
            last = merged[-1]
            merged[-1] = TextSegment(
                segment_id=last.segment_id,
                section_title=last.section_title,
                section_path=last.section_path,
                content=last.content + '\n' + buffer.content,
                page_number=last.page_number,
                segment_type=last.segment_type,
                parent_section=last.parent_section,
                metadata=dict(last.metadata),
            )

        self.segments = merged

    def _split_long_segments(self):
        """Split overlong segments."""
        new_segments = []
        for seg in self.segments:
            if len(seg.content) <= self.max_segment_len:
                new_segments.append(seg)
                continue

            # Split at paragraph boundaries.
            paragraphs = seg.content.split('\n\n')
            sub_segments = []
            current_text = ''
            
            for para in paragraphs:
                if len(current_text) + len(para) > self.max_segment_len and current_text:
                    sub_segments.append(current_text)
                    # Overlap: retain the final paragraph.
                    prev_paras = current_text.split('\n\n')
                    if self.overlap > 0 and prev_paras:
                        overlap_text = prev_paras[-1]
                        if len(overlap_text) < self.overlap:
                            current_text = overlap_text
                        else:
                            current_text = overlap_text[-self.overlap:]
                    else:
                        current_text = ''
                
                # Split at sentence boundaries when a single paragraph exceeds the limit.
                if len(para) > self.max_segment_len:
                    if current_text:
                        sub_segments.append(current_text)
                        current_text = ''
                    # Split long paragraphs into sentences.
                    sentences = self._split_by_sentence(para)
                    for sent_chunk in sentences:
                        sub_segments.append(sent_chunk)
                else:
                    if current_text:
                        current_text += '\n\n' + para
                    else:
                        current_text = para
            
            if current_text:
                sub_segments.append(current_text)

            # Keep the original segment if splitting yields only one part.
            if len(sub_segments) <= 1:
                new_segments.append(seg)
                continue

            # Create a new TextSegment.
            for sub_idx, sub_text in enumerate(sub_segments):
                sub_seg = TextSegment(
                    segment_id=f"{seg.segment_id}_{sub_idx:02d}",
                    section_title=seg.section_title,
                    section_path=list(seg.section_path),
                    content=sub_text,
                    page_number=seg.page_number,
                    segment_type=seg.segment_type,
                    parent_section=seg.parent_section,
                    metadata=dict(seg.metadata),
                )
                new_segments.append(sub_seg)

        self.segments = new_segments

    def _split_by_sentence(self, text: str) -> List[str]:
        """Split long text at sentence boundaries using max_segment_len."""
        # Sentence-ending punctuation
        sentence_end = re.compile(r'[。！？；\n](?![」』）\)])')
        
        chunks = []
        current = ''
        
        # Locate all split positions.
        positions = [m.end() for m in sentence_end.finditer(text)]
        
        if not positions:
            # Split by character count if no sentence boundary is available.
            for i in range(0, len(text), self.max_segment_len - self.overlap):
                chunk = text[i:i + self.max_segment_len]
                chunks.append(chunk)
            return chunks
        
        start = 0
        for pos in positions:
            segment = text[start:pos]
            if len(current) + len(segment) > self.max_segment_len and current:
                chunks.append(current)
                # Overlap
                if self.overlap > 0 and len(current) > self.overlap:
                    current = current[-self.overlap:]
                else:
                    current = ''
            
            if current:
                current += segment
            else:
                current = segment
            start = pos
        
        # Final segment
        if start < len(text):
            remaining = text[start:]
            if current:
                current += remaining
            else:
                current = remaining
        
        if current:
            chunks.append(current)
        
        return chunks if chunks else [text]

    def _flush_segment(self, section_info: dict, content_lines: List[str], idx: int):
        """Save the accumulated content as a segment."""
        content = '\n'.join(content_lines)
        if not content:
            return

        segment = TextSegment(
            segment_id=f"seg_{idx:04d}",
            section_title=section_info['title'],
            section_path=list(section_info['path']),
            content=content,
            page_number=0,  # python-docx does not directly expose page numbers.
            segment_type="text",
            parent_section=section_info.get('parent', ''),
        )
        self.segments.append(segment)

    def _detect_section_heading(self, text: str, para) -> Optional[dict]:
        """Detect whether text is a section heading."""
        # 1. Check pattern matches.
        for pattern in self.SECTION_PATTERNS:
            if pattern.match(text):
                return self._parse_section_heading(text, len(self.SECTION_PATTERNS))

        # 2. Check for section keywords.
        for keyword in self.SECTION_KEYWORDS:
            if keyword in text and len(text) <= 30:
                return {
                    'title': text,
                    'path': list(self._current_path()),
                    'level': 1,
                    'parent': '',
                }

        # 3. Check for a short bold heading, a common section-title format.
        if para.runs and para.runs[0].bold and len(text) <= 40:
            return {
                'title': text,
                'path': list(self._current_path()),
                'level': 1,
                'parent': '',
            }

        return None

    def _current_path(self) -> List[str]:
        """Return the current section path."""
        if self.segments:
            return self.segments[-1].section_path
        return []

    def _parse_section_heading(self, text: str, pattern_idx: int) -> dict:
        """Parse a numbered section heading."""
        # Extract the section number.
        match = re.match(r'^(\d+(?:\.\d+)*)', text)
        if match:
            num_str = match.group(1)
            path = num_str.split('.')
            level = len(path)
            return {
                'title': text,
                'path': path,
                'level': level,
                'parent': '.'.join(path[:-1]) if level > 1 else '',
            }

        # Chinese-numeral numbering
        return {
            'title': text,
            'path': [text.split('、')[0] if '、' in text else text[:5]],
            'level': 1,
            'parent': '',
        }

    # Query interface

    def get_segments_by_section(self, section_title: str) -> List[TextSegment]:
        """Return segments belonging to a specified section."""
        return [s for s in self.segments if s.section_title == section_title]

    def get_segments_by_path(self, path_prefix: List[str]) -> List[TextSegment]:
        """Return segments under a section-path prefix."""
        return [
            s for s in self.segments
            if s.section_path[:len(path_prefix)] == path_prefix
        ]

    def get_full_text(self) -> str:
        """Return the full document text."""
        return '\n\n'.join(s.content for s in self.segments)

    def summary(self) -> dict:
        """Summarize segmentation statistics."""
        sections = set(s.section_title for s in self.segments)
        return {
            'total_segments': len(self.segments),
            'unique_sections': len(sections),
            'section_names': sorted(sections),
            'avg_segment_length': (
                sum(len(s.content) for s in self.segments) / max(len(self.segments), 1)
            ),
        }


