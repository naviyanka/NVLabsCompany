"""Document parser components for the RAG pipeline.

Provides a DocumentParser Protocol and multiple implementations:
- TextParser: Splits plain text on paragraphs/sentences
- MarkdownParser: Preserves markdown structure (headers, code blocks, lists)
- CodeParser: Splits on function/class boundaries using regex patterns
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ParsedChunk:
    """A parsed chunk of a document with metadata.

    Attributes:
        content: The text content of the chunk.
        metadata: Additional metadata about the chunk (source, position, etc.).
        chunk_type: The type of chunk (paragraph, header, code_block, function, etc.).
    """

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_type: str = "text"


@runtime_checkable
class DocumentParser(Protocol):
    """Protocol defining the interface for document parsers.

    All parsers must implement parse() to split document content
    into structured chunks with metadata.
    """

    def parse(self, content: str) -> list[ParsedChunk]:
        """Parse document content into structured chunks.

        Args:
            content: The raw document content to parse.

        Returns:
            List of ParsedChunk instances with content, metadata,
            and chunk_type populated.
        """
        ...


@dataclass
class TextParser:
    """Parser for plain text documents.

    Splits text on paragraphs (double newlines) or sentences,
    depending on paragraph size relative to the max_chunk_size.

    Attributes:
        max_chunk_size: Maximum characters per chunk. Paragraphs larger
            than this are split into sentences. Defaults to 1000.
        min_chunk_size: Minimum characters for a valid chunk. Chunks
            smaller than this are merged with the next chunk. Defaults to 50.
    """

    max_chunk_size: int = 1000
    min_chunk_size: int = 0

    def parse(self, content: str) -> list[ParsedChunk]:
        """Parse plain text into paragraph/sentence chunks.

        First splits on double newlines into paragraphs. If a paragraph
        exceeds max_chunk_size, it is further split into sentences.
        Small chunks below min_chunk_size are merged with adjacent chunks.

        Args:
            content: Plain text document content.

        Returns:
            List of ParsedChunk instances with chunk_type 'paragraph' or 'sentence'.
        """
        if not content or not content.strip():
            return []

        # Split into paragraphs
        paragraphs = re.split(r"\n\n+", content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks: list[ParsedChunk] = []
        for para_idx, paragraph in enumerate(paragraphs):
            if len(paragraph) <= self.max_chunk_size:
                chunks.append(ParsedChunk(
                    content=paragraph,
                    metadata={"paragraph_index": para_idx},
                    chunk_type="paragraph",
                ))
            else:
                # Split large paragraphs into sentences
                sentences = self._split_sentences(paragraph)
                current_chunk = ""
                for sentence in sentences:
                    if (
                        current_chunk
                        and len(current_chunk) + len(sentence) > self.max_chunk_size
                    ):
                        chunks.append(ParsedChunk(
                            content=current_chunk.strip(),
                            metadata={"paragraph_index": para_idx},
                            chunk_type="sentence",
                        ))
                        current_chunk = sentence
                    else:
                        current_chunk += (" " if current_chunk else "") + sentence

                if current_chunk.strip():
                    chunks.append(ParsedChunk(
                        content=current_chunk.strip(),
                        metadata={"paragraph_index": para_idx},
                        chunk_type="sentence",
                    ))

        # Merge small chunks
        chunks = self._merge_small_chunks(chunks)
        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences using punctuation boundaries.

        Args:
            text: Text to split into sentences.

        Returns:
            List of sentence strings.
        """
        # Split on sentence-ending punctuation followed by space or end
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]

    def _merge_small_chunks(self, chunks: list[ParsedChunk]) -> list[ParsedChunk]:
        """Merge chunks smaller than min_chunk_size with adjacent chunks.

        Args:
            chunks: List of parsed chunks.

        Returns:
            List with small chunks merged into neighbors.
        """
        if not chunks:
            return []

        merged: list[ParsedChunk] = []
        for chunk in chunks:
            if (
                merged
                and len(chunk.content) < self.min_chunk_size
            ):
                # Merge with previous chunk
                merged[-1] = ParsedChunk(
                    content=merged[-1].content + "\n" + chunk.content,
                    metadata=merged[-1].metadata,
                    chunk_type=merged[-1].chunk_type,
                )
            else:
                merged.append(chunk)

        return merged


@dataclass
class MarkdownParser:
    """Parser for Markdown documents preserving structure.

    Splits markdown content respecting its structure: headers,
    code blocks, lists, and paragraphs. Each section is a separate
    chunk with appropriate metadata.

    Attributes:
        include_headers_in_chunks: Whether to include the header line
            in the chunk content. Defaults to True.
    """

    include_headers_in_chunks: bool = True

    def parse(self, content: str) -> list[ParsedChunk]:
        """Parse markdown content into structural chunks.

        Preserves markdown structure by splitting on headers and
        identifying code blocks, lists, and regular paragraphs
        within each section.

        Args:
            content: Markdown document content.

        Returns:
            List of ParsedChunk instances with chunk_type indicating
            the markdown element type (header, code_block, list, paragraph).
        """
        if not content or not content.strip():
            return []

        chunks: list[ParsedChunk] = []

        # First extract code blocks to avoid splitting inside them
        segments = self._split_preserving_code_blocks(content)

        for segment in segments:
            if segment["type"] == "code_block":
                chunks.append(ParsedChunk(
                    content=segment["content"],
                    metadata={
                        "language": segment.get("language", ""),
                    },
                    chunk_type="code_block",
                ))
            else:
                # Process non-code-block text
                section_chunks = self._parse_text_sections(segment["content"])
                chunks.extend(section_chunks)

        return chunks

    def _split_preserving_code_blocks(self, content: str) -> list[dict[str, Any]]:
        """Split content into code blocks and non-code-block segments.

        Args:
            content: Markdown content.

        Returns:
            List of segment dicts with 'type' and 'content' keys.
        """
        segments: list[dict[str, Any]] = []
        # Match fenced code blocks (``` or ~~~)
        code_block_pattern = re.compile(
            r"^(```|~~~)(\w*)\s*\n(.*?)\n\1\s*$",
            re.MULTILINE | re.DOTALL,
        )

        last_end = 0
        for match in code_block_pattern.finditer(content):
            # Add text before code block
            before = content[last_end:match.start()]
            if before.strip():
                segments.append({"type": "text", "content": before.strip()})

            # Add code block
            language = match.group(2)
            code_content = match.group(0)
            segments.append({
                "type": "code_block",
                "content": code_content,
                "language": language,
            })
            last_end = match.end()

        # Add remaining text
        remaining = content[last_end:]
        if remaining.strip():
            segments.append({"type": "text", "content": remaining.strip()})

        # If no code blocks found, return entire content as text
        if not segments:
            segments.append({"type": "text", "content": content.strip()})

        return segments

    def _parse_text_sections(self, content: str) -> list[ParsedChunk]:
        """Parse non-code-block markdown text into sections.

        Splits on headers and identifies lists within sections.

        Args:
            content: Markdown text (without code blocks).

        Returns:
            List of ParsedChunk instances.
        """
        chunks: list[ParsedChunk] = []

        # Split on header lines
        sections = re.split(r"(?=^#{1,6}\s+)", content, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Check if this section starts with a header
            header_match = re.match(r"^(#{1,6})\s+(.+?)$", section, re.MULTILINE)
            header_level = 0
            header_text = ""

            if header_match:
                header_level = len(header_match.group(1))
                header_text = header_match.group(2).strip()

            # Check if content is primarily a list
            lines = section.split("\n")
            non_header_lines = lines[1:] if header_match else lines
            list_lines = [
                line for line in non_header_lines
                if re.match(r"^\s*[-*+]\s+|^\s*\d+\.\s+", line)
            ]

            if list_lines and len(list_lines) >= len(non_header_lines) * 0.5:
                chunk_type = "list"
            elif header_match:
                chunk_type = "header"
            else:
                chunk_type = "paragraph"

            metadata: dict[str, Any] = {}
            if header_level:
                metadata["header_level"] = header_level
                metadata["header_text"] = header_text

            chunk_content = section if self.include_headers_in_chunks else (
                "\n".join(non_header_lines).strip() if header_match else section
            )

            if chunk_content.strip():
                chunks.append(ParsedChunk(
                    content=chunk_content,
                    metadata=metadata,
                    chunk_type=chunk_type,
                ))

        return chunks


@dataclass
class CodeParser:
    """Parser for source code files.

    Splits code on function/class boundaries using regex patterns.
    Supports Python, JavaScript, and TypeScript. Falls back to
    line-based splitting for unrecognized languages.

    Attributes:
        language: Programming language hint ('python', 'javascript', 'typescript').
            If None, attempts auto-detection. Defaults to None.
        max_chunk_size: Maximum characters per chunk. Large functions/classes
            are kept whole but flagged in metadata. Defaults to 2000.
    """

    language: str | None = None
    max_chunk_size: int = 2000

    # Regex patterns for function/class boundaries by language
    _PATTERNS: dict[str, list[re.Pattern[str]]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize regex patterns for supported languages."""
        self._PATTERNS = {
            "python": [
                # Match class definitions
                re.compile(
                    r"^(class\s+\w+[^:]*:.*?)(?=\n(?:class\s|\S)|\Z)",
                    re.MULTILINE | re.DOTALL,
                ),
                # Match function definitions (including async)
                re.compile(
                    r"^((?:async\s+)?def\s+\w+\([^)]*\)[^:]*:.*?)(?=\n(?:(?:async\s+)?def\s|class\s|\S)|\Z)",
                    re.MULTILINE | re.DOTALL,
                ),
            ],
            "javascript": [
                # Match function declarations and arrow functions
                re.compile(
                    r"^((?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)\s*\{.*?\n\})",
                    re.MULTILINE | re.DOTALL,
                ),
                # Match class declarations
                re.compile(
                    r"^((?:export\s+)?class\s+\w+[^{]*\{.*?\n\})",
                    re.MULTILINE | re.DOTALL,
                ),
            ],
            "typescript": [
                # Match function declarations
                re.compile(
                    r"^((?:export\s+)?(?:async\s+)?function\s+\w+[^{]*\{.*?\n\})",
                    re.MULTILINE | re.DOTALL,
                ),
                # Match class declarations
                re.compile(
                    r"^((?:export\s+)?class\s+\w+[^{]*\{.*?\n\})",
                    re.MULTILINE | re.DOTALL,
                ),
                # Match interface declarations
                re.compile(
                    r"^((?:export\s+)?interface\s+\w+[^{]*\{.*?\n\})",
                    re.MULTILINE | re.DOTALL,
                ),
            ],
        }

    def parse(self, content: str) -> list[ParsedChunk]:
        """Parse source code into function/class boundary chunks.

        Uses language-specific regex patterns to identify code blocks.
        Falls back to line-based splitting if no patterns match or
        the language is not recognized.

        Args:
            content: Source code content.

        Returns:
            List of ParsedChunk instances with chunk_type indicating
            the code element type (function, class, module_level, block).
        """
        if not content or not content.strip():
            return []

        language = self.language or self._detect_language(content)
        chunks: list[ParsedChunk] = []

        if language == "python":
            chunks = self._parse_python(content)
        elif language in ("javascript", "typescript"):
            chunks = self._parse_js_ts(content, language)
        else:
            chunks = self._parse_generic(content)

        return chunks if chunks else self._parse_generic(content)

    def _detect_language(self, content: str) -> str:
        """Attempt to detect the programming language from content.

        Uses heuristic checks for common language indicators.

        Args:
            content: Source code content.

        Returns:
            Detected language string or 'unknown'.
        """
        if re.search(r"^(?:from|import)\s+\w+", content, re.MULTILINE):
            if re.search(r"^\s*def\s+\w+", content, re.MULTILINE):
                return "python"
        if re.search(r"(?:interface|type)\s+\w+\s*[{=]", content):
            return "typescript"
        if re.search(r"(?:function|const|let|var)\s+\w+", content):
            return "javascript"
        return "unknown"

    def _parse_python(self, content: str) -> list[ParsedChunk]:
        """Parse Python source code into chunks.

        Identifies classes and functions by indentation-aware splitting.

        Args:
            content: Python source code.

        Returns:
            List of ParsedChunk instances.
        """
        chunks: list[ParsedChunk] = []
        lines = content.split("\n")

        current_block: list[str] = []
        current_type = "module_level"
        current_name = ""

        for line in lines:
            # Check for top-level class or function definition
            class_match = re.match(r"^class\s+(\w+)", line)
            func_match = re.match(r"^(?:async\s+)?def\s+(\w+)", line)

            if class_match or func_match:
                # Save current block if non-empty
                if current_block:
                    block_content = "\n".join(current_block).strip()
                    if block_content:
                        chunks.append(ParsedChunk(
                            content=block_content,
                            metadata={"name": current_name, "language": "python"},
                            chunk_type=current_type,
                        ))

                # Start new block
                current_block = [line]
                if class_match:
                    current_type = "class"
                    current_name = class_match.group(1)
                else:
                    current_type = "function"
                    current_name = func_match.group(1)
            else:
                current_block.append(line)

        # Don't forget the last block
        if current_block:
            block_content = "\n".join(current_block).strip()
            if block_content:
                chunks.append(ParsedChunk(
                    content=block_content,
                    metadata={"name": current_name, "language": "python"},
                    chunk_type=current_type,
                ))

        return chunks

    def _parse_js_ts(self, content: str, language: str) -> list[ParsedChunk]:
        """Parse JavaScript/TypeScript source code into chunks.

        Identifies functions, classes, and interfaces by regex patterns.

        Args:
            content: JS/TS source code.
            language: 'javascript' or 'typescript'.

        Returns:
            List of ParsedChunk instances.
        """
        chunks: list[ParsedChunk] = []
        lines = content.split("\n")

        current_block: list[str] = []
        current_type = "module_level"
        current_name = ""

        for line in lines:
            # Check for function/class/interface declarations
            func_match = re.match(
                r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", line
            )
            class_match = re.match(r"^(?:export\s+)?class\s+(\w+)", line)
            interface_match = re.match(
                r"^(?:export\s+)?interface\s+(\w+)", line
            ) if language == "typescript" else None

            if func_match or class_match or interface_match:
                # Save current block
                if current_block:
                    block_content = "\n".join(current_block).strip()
                    if block_content:
                        chunks.append(ParsedChunk(
                            content=block_content,
                            metadata={"name": current_name, "language": language},
                            chunk_type=current_type,
                        ))

                current_block = [line]
                if class_match:
                    current_type = "class"
                    current_name = class_match.group(1)
                elif interface_match:
                    current_type = "interface"
                    current_name = interface_match.group(1)
                else:
                    current_type = "function"
                    current_name = func_match.group(1)
            else:
                current_block.append(line)

        # Last block
        if current_block:
            block_content = "\n".join(current_block).strip()
            if block_content:
                chunks.append(ParsedChunk(
                    content=block_content,
                    metadata={"name": current_name, "language": language},
                    chunk_type=current_type,
                ))

        return chunks

    def _parse_generic(self, content: str) -> list[ParsedChunk]:
        """Parse code using line-based splitting as a fallback.

        Splits content into fixed-size blocks when no language-specific
        patterns can be applied.

        Args:
            content: Source code content.

        Returns:
            List of ParsedChunk instances with chunk_type 'block'.
        """
        chunks: list[ParsedChunk] = []
        lines = content.split("\n")

        # Split into blocks of roughly max_chunk_size characters
        current_block: list[str] = []
        current_size = 0

        for line in lines:
            line_size = len(line) + 1  # +1 for newline
            if current_size + line_size > self.max_chunk_size and current_block:
                block_content = "\n".join(current_block).strip()
                if block_content:
                    chunks.append(ParsedChunk(
                        content=block_content,
                        metadata={"language": self.language or "unknown"},
                        chunk_type="block",
                    ))
                current_block = [line]
                current_size = line_size
            else:
                current_block.append(line)
                current_size += line_size

        # Last block
        if current_block:
            block_content = "\n".join(current_block).strip()
            if block_content:
                chunks.append(ParsedChunk(
                    content=block_content,
                    metadata={"language": self.language or "unknown"},
                    chunk_type="block",
                ))

        return chunks
