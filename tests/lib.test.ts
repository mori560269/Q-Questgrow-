import { describe, expect, it } from "vitest";
import { EDGES, NODES, SESSIONS, PEOPLE } from "../src/data/event";
import { cancel, emptyLedger, reserve } from "../src/lib/reservation";
import { shortestPath } from "../src/lib/route";
import { rankMatches } from "../src/lib/matching";
import { answerLocally, searchSessions, triageLocally } from "../src/lib/nlp";

const byId = (id: string) => SESSIONS.find((s) => s.id === id)!;

describe("reservation", () => {
  it("books, detects conflicts, waitlists and promotes", () => {
    let ledger = emptyLedger();
    const w2 = byId("w2");
    const r1 = reserve(ledger, SESSIONS, w2, "u1");
    expect(r1.ok && r1.status).toBe("booked");
    if (!r1.ok) throw 0;
    ledger = r1.ledger;

    // w3 は w2 と同時刻
    const r2 = reserve(ledger, SESSIONS, byId("w3"), "u1");
    expect(r2.ok).toBe(false);
    if (!r2.ok) expect(r2.conflictWith?.id).toBe("w2");

    // 定員20のうち19席が他で埋まっている → u2 で満席、u3 はキャンセル待ち
    const r3 = reserve(ledger, SESSIONS, w2, "u2", 18);
    if (!r3.ok) throw 0;
    const r4 = reserve(r3.ledger, SESSIONS, w2, "u3", 18);
    expect(r4.ok && r4.status).toBe("waitlisted");
    if (!r4.ok) throw 0;

    const c = cancel(r4.ledger, w2, "u1", 18);
    expect(c.promoted).toBe("u3");
    expect(c.ledger.booked.w2).toEqual(["u2", "u3"]);
  });
});

describe("route", () => {
  it("finds a path and can avoid stairs", () => {
    const fast = shortestPath(NODES, EDGES, "n_booths", "n_main")!;
    const flat = shortestPath(NODES, EDGES, "n_booths", "n_main", { avoidStairs: true })!;
    expect(fast.path).toEqual(["n_booths", "n_top", "n_main"]);
    expect(flat.path.join(">")).not.toContain("n_booths>n_top");
    expect(flat.distance).toBeGreaterThan(fast.distance);
  });
});

describe("matching", () => {
  it("ranks people with shared interests first", () => {
    const ranked = rankMatches({ id: "me", interests: ["AI", "テクノロジー", "科学"], goals: ["学びたい"] }, PEOPLE);
    expect(ranked[0].person.id).toBe("p3");
  });
});

describe("nlp", () => {
  it("searches sessions from natural language", () => {
    const { hits } = searchSessions("午後のAIのワークショップ");
    expect(hits[0].session.id).toBe("w1");
  });
  it("answers faq and places locally", () => {
    const ctx = { now: 700, myBookings: [], delays: {}, announcements: [] };
    expect(answerLocally("トイレはどこ？", ctx)).toContain("[[map:wc]]");
    expect(answerLocally("Wi-Fiある？", ctx)).toContain("TEDxQuestgrow-Guest");
    expect(answerLocally("荷物を預けたい", ctx)).toContain("クローク");
  });
  it("triages urgent inquiries", () => {
    const t = triageLocally("ロビーで人が倒れています");
    expect(t.category).toBe("medical");
    expect(t.urgency).toBe("high");
    expect(triageLocally("財布を落としました").category).toBe("lost");
  });
});
