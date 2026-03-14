import re
import codecs

with codecs.open("app/index.html", "r", "utf-8", errors="ignore") as f:
    text = f.read()

text = re.sub(r'<span class="trace-label">.*?</span>', '<span class="trace-label">⟨THOUGHT_TRACE⟩</span>', text)

with codecs.open("app/index.html", "w", "utf-8") as f:
    f.write(text)

print("Successfully replaced all trace labels with ⟨THOUGHT_TRACE⟩")
