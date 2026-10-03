import assert from "node:assert/strict";
import { test } from "node:test";
import { ConversationRuntime } from "../src/runtime/ConversationRuntime.ts";

for (const campaign of ["product_promoter", "card_promoter", "loan_promoter"]) {
  for (const language of ["ru", "kk"]) {
    test(`${campaign}: final ${language} response controls TTS despite stale model/transcript`, async () => {
      const played = [];
      const other = language === "ru" ? "kk" : "ru";
      const response = {
        response_text:
          language === "ru"
            ? "Можно рассказать об условиях?"
            : "Шарттарын айтып берейін бе?",
        scenario_pack_id: campaign,
        conversation_status: "awaiting_user",
        state: {
          response_language: language,
          preferred_response_language: language,
        },
        routing: {
          kind: "language_control",
          response_language: language,
          language: other,
        },
        trace: { language: other },
      };
      const runtime = new ConversationRuntime(
        { sendMessage: async () => response },
        {
          speak: async (text, locale) => {
            played.push({ text, locale });
            return {};
          },
          stop() {},
        },
      );
      await runtime.startConversation();
      await runtime.handleTranscript({
        text: "Language control",
        language: other,
      });
      assert.deepEqual(played, [
        { text: response.response_text, locale: language },
      ]);
      assert.equal(
        runtime.getSnapshot().messages.at(-1).text,
        response.response_text,
      );
      runtime.dispose();
    });
  }
}
