const ORDINALS = [
  "", "Pertama", "Kedua", "Ketiga", "Keempat", "Kelima",
  "Keenam", "Ketujuh", "Kedelapan", "Kesembilan", "Kesepuluh",
];

export function normalizeSpeechText(text) {
  return String(text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/https?:\/\/\S+/g, " tautan ")
    .replace(/^\s*#{1,6}\s+/gm, "")
    .replace(/^\s*(\d{1,2})[.)]\s+/gm, (_, value) => `${ORDINALS[Number(value)] || `Nomor ${value}`}, `)
    .replace(/^\s*[-*•]\s+/gm, "")
    .replace(/[;]+/g, ",")
    .replace(/[:]+(?=\s)/g, ",")
    .replace(/[!?]{2,}/g, (value) => value[0])
    .replace(/\.{3,}/g, ".")
    .replace(/[*_`#>|~]/g, " ")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/([.!?,])?\s*\n{2,}\s*/g, (_, punctuation) => punctuation ? `${punctuation} ` : ". ")
    .replace(/\s*\n\s*/g, " ")
    .replace(/\s+([,.;!?])/g, "$1")
    .replace(/([.!?])(?=[A-Za-zÀ-ÿ])/g, "$1 ")
    .replace(/,{2,}/g, ",")
    .replace(/([.!?]){2,}/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function splitLongSentence(sentence, maxLength) {
  if (sentence.length <= maxLength) return [sentence];
  const parts = [];
  const words = sentence.split(/\s+/);
  let current = "";
  for (const word of words) {
    if (current && current.length + word.length + 1 > maxLength) {
      parts.push(current);
      current = word;
    } else {
      current = current ? `${current} ${word}` : word;
    }
  }
  if (current) parts.push(current);
  return parts;
}

export function bufferSpeechSentences(
  text,
  { targetLength = 320, minLength = 55, maxLength = 900 } = {},
) {
  const normalized = normalizeSpeechText(text);
  if (!normalized) return [];
  const sentences = normalized.match(/[^.!?]+(?:[.!?]+|$)/g) || [normalized];
  const chunks = [];
  let current = "";
  for (const rawSentence of sentences) {
    const sentence = rawSentence.trim();
    if (!sentence) continue;
    for (const part of splitLongSentence(sentence, maxLength)) {
      const combined = current ? `${current} ${part}` : part;
      if (current && combined.length > maxLength && current.length >= minLength) {
        chunks.push(current);
        current = part;
      } else {
        current = combined;
      }
      if (current.length >= targetLength && /[.!?]$/.test(current)) {
        chunks.push(current);
        current = "";
      }
    }
  }
  if (current) {
    if (chunks.length && current.length < minLength) {
      chunks[chunks.length - 1] = `${chunks[chunks.length - 1]} ${current}`;
    } else {
      chunks.push(current);
    }
  }
  return chunks;
}

export function segmentPauseMs(text) {
  const ending = String(text || "").trim().slice(-1);
  if (ending === "?" || ending === "!") return 75;
  if (ending === ".") return 55;
  if (ending === ",") return 20;
  return 25;
}
