import type { Person } from "../data/event";

export type Match = { person: Person; score: number; shared: string[]; reasons: string[] };

const COMPLEMENT: Record<string, string[]> = {
  "投資・支援": ["仲間を探したい", "コラボ相手を探す"],
  "採用・転職": ["仲間を探したい", "コラボ相手を探す"],
  "学びたい": ["アイデアを話したい"],
};

function complements(a: string[], b: string[]): string[] {
  const hits: string[] = [];
  for (const g of a) for (const c of COMPLEMENT[g] ?? []) if (b.includes(c)) hits.push(`${g} ↔ ${c}`);
  for (const g of b) for (const c of COMPLEMENT[g] ?? []) if (a.includes(c)) hits.push(`${c} ↔ ${g}`);
  return [...new Set(hits)];
}

/**
 * 興味の Jaccard 係数（重み0.7）と目的の一致・補完（重み0.3）でスコア化。
 * 登壇者・スタッフは「話しかけやすさ」を少し加点する。
 */
export function scoreMatch(me: Pick<Person, "interests" | "goals">, other: Person): Match {
  const shared = me.interests.filter((i) => other.interests.includes(i));
  const union = new Set([...me.interests, ...other.interests]).size || 1;
  const interestScore = shared.length / union;

  const sameGoals = me.goals.filter((g) => other.goals.includes(g));
  const comp = complements(me.goals, other.goals);
  const goalScore = Math.min(1, sameGoals.length * 0.5 + comp.length * 0.6);

  const bonus = other.role === "speaker" ? 0.05 : 0;
  const score = Math.min(1, interestScore * 0.7 + goalScore * 0.3 + bonus);

  const reasons: string[] = [];
  if (shared.length) reasons.push(`共通の関心: ${shared.join("・")}`);
  if (sameGoals.length) reasons.push(`同じ目的: ${sameGoals.join("・")}`);
  if (comp.length) reasons.push(`目的がかみ合う: ${comp.join(" / ")}`);
  return { person: other, score, shared, reasons };
}

export function rankMatches(me: Pick<Person, "id" | "interests" | "goals">, people: Person[]): Match[] {
  return people
    .filter((p) => p.id !== me.id)
    .map((p) => scoreMatch(me, p))
    .sort((a, b) => b.score - a.score);
}
