import re
import markdown2
from jinja2 import Template

EMAIL_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <style>
    body {
      font-family: Arial, sans-serif;
      line-height: 1.6;
      padding: 20px;
    }
    .email-container {
      background-color: #f9f9f9;
      border: 1px solid #ddd;
      padding: 20px;
      border-radius: 6px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 1em;
    }
    th, td {
      padding: 8px 12px;
      border: 1px solid #ccc;
      text-align: left;
    }
    th {
      background-color: #f0f0f0;
    }
    blockquote {
      border-left: 4px solid #ccc;
      margin: 1em 0;
      padding-left: 1em;
      color: #555;
    }
  </style>
</head>
<body>
  <div class="email-container">
    {{ body | safe }}
  </div>
</body>
</html>
"""

def markdown_table_to_text_table(md_table: str) -> str:
    lines = md_table.strip().split("\n")
    if len(lines) < 2:
        return md_table
    header = lines[0].split('|')[1:-1]
    rows = [line.split('|')[1:-1] for line in lines[2:] if line.strip()]
    widths = [max(len(cell.strip()) for cell in col) for col in zip(header, *rows)]
    def fmt(row): return " | ".join(cell.strip().ljust(w) for cell, w in zip(row, widths))
    border = "-+-".join('-' * w for w in widths)
    return f"{fmt(header)}\n{border}\n" + "\n".join(fmt(r) for r in rows)

def convert_to_email_template(model_reply: str) -> str:
    def heading_sub(match):
        level = len(match.group(1))
        title = match.group(2).strip().upper()
        underline = "=" * len(title) if level == 1 else "-" * len(title)
        return f"{title}\n{underline}"

    def blockquote_sub(match):
        content = match.group(1).strip()
        if content.lower().startswith("note:"):
            return f"[NOTE] {content[5:].strip()}"
        elif content.lower().startswith("warning:"):
            return f"[WARNING] {content[8:].strip()}"
        return f"> {content}"

    def table_sub(match):
        return markdown_table_to_text_table(match.group(0))

    def is_markdown(text):
        return bool(re.search(r"(#{1,6}\s+|\*\*|__|\[.*?\]\(.*?\)|`{1,3}|^\|)", text, re.MULTILINE))

    if is_markdown(model_reply):
        html_body = markdown2.markdown(model_reply, extras=["tables", "fenced-code-blocks"])
        template = Template(EMAIL_HTML_TEMPLATE)
        return template.render(body=html_body)

    # Plain text fallback
    text = model_reply
    text = re.sub(r"^(#{1,6})\s+(.*)", heading_sub, text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", lambda m: m.group(1).upper(), text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    text = re.sub(r"```\w*\n(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`{1,2}(.*?)`{1,2}", r"\1", text)
    text = re.sub(r"^[ \t]*>[ \t]?(.*)", blockquote_sub, text, flags=re.MULTILINE)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1 (\2)", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"^[ \t]*[-*•]+[ \t]+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"^[ \t]*(\d+)[.)][ \t]+", r"\1) ", text, flags=re.MULTILINE)
    text = re.sub(r"((?:\|.*\n)+)", table_sub, text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)

    return text.strip()
