export default function refineLLMText(raw = "") {
  return raw
    .replace(/\\n/g, " ")               // kill back‑slash n
    .replace(/\s{2,}/g, " ")            // collapse extra spaces
    .replace(/\*\*(.*?)\*\*/g, "<b>$1</b>") // **bold** → <b>bold</b>
    .trim();
}