import { describe, expect, it } from "vitest";
import { buildCitationOrder, extractEvidenceIds, parseCitationMarkers, stripCitationMarkers } from "@/lib/citations";

const EV_A = "ev_1a2b3c4d5e6f7890";
const EV_B = "ev_00112233445566aa";

describe("parseCitationMarkers", () => {
  it("returns an empty array for empty input", () => {
    expect(parseCitationMarkers("")).toEqual([]);
  });

  it("returns a single text segment when there are no markers", () => {
    expect(parseCitationMarkers("Revenue grew 15% year over year.")).toEqual([
      { type: "text", value: "Revenue grew 15% year over year." },
    ]);
  });

  it("parses a single marker surrounded by text", () => {
    const segments = parseCitationMarkers(`Revenue grew 15%[${EV_A}] year over year.`);
    expect(segments).toEqual([
      { type: "text", value: "Revenue grew 15%" },
      { type: "citation", evidenceId: EV_A, raw: `[${EV_A}]` },
      { type: "text", value: " year over year." },
    ]);
  });

  it("parses multiple markers, including back-to-back markers with no text between them", () => {
    const segments = parseCitationMarkers(`[${EV_A}][${EV_B}] combined evidence`);
    expect(segments).toEqual([
      { type: "citation", evidenceId: EV_A, raw: `[${EV_A}]` },
      { type: "citation", evidenceId: EV_B, raw: `[${EV_B}]` },
      { type: "text", value: " combined evidence" },
    ]);
  });

  it("lower-cases the evidence id even if the marker used upper case", () => {
    const segments = parseCitationMarkers(`[EV_1A2B3C4D5E6F7890]`);
    expect(segments).toEqual([{ type: "citation", evidenceId: EV_A, raw: "[EV_1A2B3C4D5E6F7890]" }]);
  });

  it("leaves an unclosed bracket as plain text", () => {
    const text = `Figures cite [ev_1a2b3c4d5e6f7890 but the bracket never closes.`;
    expect(parseCitationMarkers(text)).toEqual([{ type: "text", value: text }]);
  });

  it("leaves an empty ev_ marker as plain text", () => {
    const text = "This claim has [ev_] which is not a real id.";
    expect(parseCitationMarkers(text)).toEqual([{ type: "text", value: text }]);
  });

  it("leaves a too-short hex id as plain text", () => {
    const text = "Too short: [ev_abc]";
    expect(parseCitationMarkers(text)).toEqual([{ type: "text", value: text }]);
  });

  it("leaves non-hex characters inside the id as plain text", () => {
    const text = "Not hex: [ev_zzzzzzzzzzzzzzzz]";
    expect(parseCitationMarkers(text)).toEqual([{ type: "text", value: text }]);
  });

  it("treats doubled brackets as an outer literal bracket plus one real marker", () => {
    const segments = parseCitationMarkers(`[[${EV_A}]]`);
    expect(segments).toEqual([
      { type: "text", value: "[" },
      { type: "citation", evidenceId: EV_A, raw: `[${EV_A}]` },
      { type: "text", value: "]" },
    ]);
  });
});

describe("extractEvidenceIds", () => {
  it("returns evidence ids in order of first appearance, deduplicated", () => {
    const text = `[${EV_A}] and again [${EV_B}] and once more [${EV_A}]`;
    expect(extractEvidenceIds(text)).toEqual([EV_A, EV_B]);
  });

  it("returns an empty array when there are no markers", () => {
    expect(extractEvidenceIds("no citations here")).toEqual([]);
  });
});

describe("stripCitationMarkers", () => {
  it("removes markers and collapses the resulting double space", () => {
    expect(stripCitationMarkers(`Revenue grew 15% [${EV_A}] year over year.`)).toBe(
      "Revenue grew 15% year over year.",
    );
  });

  it("trims leading/trailing whitespace left behind by a removed marker", () => {
    expect(stripCitationMarkers(`[${EV_A}] Revenue grew.`)).toBe("Revenue grew.");
  });

  it("returns the original text unchanged when there are no markers", () => {
    expect(stripCitationMarkers("No markers at all.")).toBe("No markers at all.");
  });
});

describe("buildCitationOrder", () => {
  it("numbers evidence ids in order of first appearance across multiple texts", () => {
    const order = buildCitationOrder([`Para one cites [${EV_B}].`, `Para two cites [${EV_A}] then [${EV_B}] again.`]);
    expect(order.get(EV_B)).toBe(1);
    expect(order.get(EV_A)).toBe(2);
    expect(order.size).toBe(2);
  });

  it("returns an empty map when no text has any markers", () => {
    expect(buildCitationOrder(["plain text", "more plain text"]).size).toBe(0);
  });
});
