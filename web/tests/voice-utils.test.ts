import { describe, expect, it } from "vitest";
import { UI_KEYS_EN, UI_KEYS_TA, t } from "@/lib/ui-strings";
import { containsTamil, hasWakeWord, pickVoice, rateFor, recognitionLocale, stripWakeWord } from "@/lib/voice-utils";
import { roundTop } from "@/components/BarChart";

describe("wake word", () => {
  it.each([
    ["Wensday, nalaiku 9 mani meeting remind pannu", "nalaiku 9 mani meeting remind pannu"],
    ["wednesday remind me at 5", "remind me at 5"],            // recognisers hear "Wednesday"
    ["Hey Wensday: saptiya?", "saptiya?"],
    ["வென்ஸ்டே நாளை மீட்டிங்", "நாளை மீட்டிங்"],
    ["nalaiku meeting", "nalaiku meeting"],                     // no wake word -> untouched
  ])("strips %s", (input, expected) => expect(stripWakeWord(input)).toBe(expected));

  it("detects the wake word only when addressed", () => {
    expect(hasWakeWord("Wensday, hello")).toBe(true);
    expect(hasWakeWord("ok so wensday what time is it")).toBe(true);
    expect(hasWakeWord("we talked on a rainy day")).toBe(false);
    expect(hasWakeWord("")).toBe(false);
  });
});

describe("voice selection", () => {
  const voices = [
    { name: "Microsoft Valluvar - Tamil (India)", lang: "ta-IN" },
    { name: "Microsoft Pallavi Online (Natural) - Tamil (India)", lang: "ta-IN" },
    { name: "Microsoft David - English (United States)", lang: "en-US" },
    { name: "Microsoft Neerja Online (Natural) - English (India)", lang: "en-IN" },
    { name: "Google UK English Female", lang: "en-GB" },
  ];

  it("prefers the female Tamil voice over the male one", () => expect(pickVoice(voices, "ta")?.name).toContain("Pallavi"));
  it("prefers en-IN (South-Indian accent) for English", () => expect(pickVoice(voices, "en")?.name).toContain("Neerja"));
  it("honours server-advertised hints first", () => expect(pickVoice(voices, "en", ["Google UK"])?.name).toBe("Google UK English Female"));
  it("avoids known-male voices when nothing is known-female", () => {
    expect(pickVoice([{ name: "Ravi", lang: "en-IN" }, { name: "Asha", lang: "en-IN" }], "en")?.name).toBe("Asha");
  });
  it("returns null when the platform has no voice for the language", () => expect(pickVoice([{ name: "x", lang: "fr-FR" }], "ta")).toBeNull());
  it("speaks Tamil a little slower and clamps the rate", () => {
    expect(rateFor("ta", 1)).toBeLessThan(rateFor("en", 1));
    expect(rateFor("en", 10)).toBe(2);
    expect(rateFor("en", 0.01)).toBe(0.5);
  });
});

describe("recognition locale", () => {
  it("auto: English/Tanglish by default, Tamil once the user speaks Tamil", () => {
    expect(recognitionLocale("auto", null)).toBe("en-IN");
    expect(recognitionLocale("auto", "tg")).toBe("en-IN");
    expect(recognitionLocale("auto", "ta")).toBe("ta-IN");
  });
  it("an explicit preference always wins", () => expect(recognitionLocale("ta-IN", "en")).toBe("ta-IN"));
  it("detects Tamil script", () => { expect(containsTamil("நாளை")).toBe(true); expect(containsTamil("nalaiku")).toBe(false); });
});

describe("UI strings", () => {
  it("has a Tamil string for every English key (and no orphans)", () => expect([...UI_KEYS_TA].sort()).toEqual([...UI_KEYS_EN].sort()));
  it("never returns an empty label", () => { for (const k of UI_KEYS_EN) { expect(t("en", k).length).toBeGreaterThan(0); expect(t("ta", k).length).toBeGreaterThan(0); } });
});

describe("chart geometry", () => {
  it("rounds only the data end of a column", () => {
    const d = roundTop(10, 20, 24, 60, 4);
    expect(d.startsWith("M10,80")).toBe(true);           // starts on the baseline, square
    expect(d).toContain("Q10,20 14,20");                // rounded top-left
    expect(roundTop(0, 0, 10, 2, 4)).toContain("Q0,0 2,0"); // a short bar clamps the radius so it never inverts
  });
});
