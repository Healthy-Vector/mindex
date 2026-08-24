export const EVIDENCE_FIELDS = {
  legalRight: "법적 권리",
  exploitationMode: "사업적 이용형태",
  territory: "지역",
  period: "기간",
  exclusivity: "독점 형태",
};

export function evidenceEntries(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

export function firstEvidenceEntry(evidence, field) {
  return evidenceEntries(evidence?.[field])[0] ?? {};
}

export function updateFirstEvidenceEntry(evidence, field, patch) {
  const entries = evidenceEntries(evidence?.[field]);
  const first = entries[0] ?? { location: "본문", page: 1, clause: "", quote: "", confidence: null };
  return {
    ...evidence,
    [field]: [{ ...first, ...patch }, ...entries.slice(1)],
  };
}

export function missingEvidenceFields(evidence) {
  return Object.keys(EVIDENCE_FIELDS).filter((field) =>
    !evidenceEntries(evidence?.[field]).some((entry) => entry?.quote?.trim()),
  );
}

export function groupEvidenceByQuote(evidence) {
  const byQuote = new Map();
  for (const [field, rawEntries] of Object.entries(evidence ?? {})) {
    for (const entry of evidenceEntries(rawEntries)) {
      const quote = entry?.quote?.trim();
      if (!quote) continue;
      const group = byQuote.get(quote) ?? { quote, clauses: new Set(), fields: [] };
      if (entry.clause) group.clauses.add(entry.clause);
      if (!group.fields.includes(field)) group.fields.push(field);
      byQuote.set(quote, group);
    }
  }
  return [...byQuote.values()].map((group) => ({ ...group, clauses: [...group.clauses] }));
}
