# Visual OCR Non-Text Boundary

## Problem

WeChat OCR may read words printed inside an image, card, poster, thumbnail, or attachment and surface them as plain text. If that visual text is treated as a customer-authored chat message, it can pollute four places:

- current reply batch
- conversation history sent to Brain
- raw-message learning / RAG experience intake
- later short social replies that revive stale history

This is a generic carrier-boundary problem. It must not be fixed by blocking a specific word, brand, product, customer, industry, or account.

## Boundary

Only customer-authored chat text may enter customer intent, Brain current-message reasoning, conversation history, or learning.

Text extracted from non-text visual carriers is capture/audit metadata. It is not a customer request, product fact, customer preference, or learnable experience unless a future human or trusted upstream explicitly reclassifies it as real chat text.

## Minimal Implementation

1. Shared message envelope helper detects visual/media OCR from source metadata, message type, quality flags, and nested OCR item metadata.
2. Scheduler and direct workflow batch selection skip visual/media OCR records before they become reply input.
3. Raw-message learning marks visual/media OCR as non-learnable.
4. Conversation history assembler excludes visual/media OCR records so old image text cannot be sent back into Brain as dialogue.
5. Brain quality gate rejects pure social turns that proactively revive stale unsupported business/entity context. Short greetings such as "你好" or "在吗" should answer the current turn briefly unless the customer explicitly asks to continue prior business.

## Non-Goals

- Do not rename CLI commands, JSON fields, paths, variables, or public functions.
- Do not add product/account-specific keyword blacklists.
- Do not let local guards author replacement customer-visible wording; they only reject and ask Brain to repair.
- Do not clean historical runtime data as part of this fix. Historical cleanup is a separate maintenance task.

## Test Requirements

- A text record with `source_type=image_ocr` or `quality_flags=["visual_ocr_non_text"]` is not reply-eligible.
- The same visible content without visual/media OCR metadata remains reply-eligible.
- Raw learning excludes visual/media OCR.
- Conversation history skips visual/media OCR but keeps normal chat text.
- Brain quality verification rejects a pure greeting reply that reopens an old unsupported business/entity topic.
