import test from "node:test";
import assert from "node:assert/strict";
import { bufferSpeechSentences, normalizeSpeechText, segmentPauseMs } from "./voice-engine.js";

test("normalizes whitespace, markdown, and bullets", () => {
  assert.equal(normalizeSpeechText("## Ringkasan\n\n- Satu   hal\n- Dua hal"), "Ringkasan Satu hal Dua hal");
});

test("buffers complete sentences instead of tiny chunks", () => {
  const chunks = bufferSpeechSentences(
    "Ini pendek. Ini juga pendek. Kalimat ketiga melanjutkan penjelasan dengan ritme percakapan yang alami.",
    { targetLength: 70, minLength: 40, maxLength: 180 },
  );
  assert.deepEqual(chunks, ["Ini pendek. Ini juga pendek. Kalimat ketiga melanjutkan penjelasan dengan ritme percakapan yang alami."]);
});

test("keeps commas inside a sentence", () => {
  const chunks = bufferSpeechSentences(
    "Pertama, buka dashboard, lalu pilih agent yang ingin diperbarui. Setelah itu, simpan perubahan.",
    { targetLength: 45, minLength: 20, maxLength: 120 },
  );
  assert.deepEqual(chunks, [
    "Pertama, buka dashboard, lalu pilih agent yang ingin diperbarui.",
    "Setelah itu, simpan perubahan.",
  ]);
});

test("uses sub-200ms punctuation pauses", () => {
  assert.equal(segmentPauseMs("lanjut,"), 20);
  assert.equal(segmentPauseMs("selesai."), 55);
  assert.ok(segmentPauseMs("bertanya?") < 200);
});
