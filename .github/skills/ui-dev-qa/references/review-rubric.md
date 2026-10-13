# Independent UI review rubric

Use this with a fresh session (or subagent) that did NOT build the screens. A
model that built a screen tends to approve it, so the reviewer must start cold.
The reviewer must be able to read images; if it cannot, stop and say so.

## Reviewer instructions
You are a QA engineer reviewing screenshots of a web app. You are not asked to
approve or reject. List defects only. For each screenshot, work through the
checks below and report every problem you can see, even small ones. Do not
praise the design. Do not suggest redesigns.

## Output format
One line per defect:
`<screenshot file> | <location in the screenshot> | <what is wrong> | <severity: P0 blocks use, P1 looks broken, P2 polish>`

End with: "Screens reviewed: N. Screens with no defects: M." If you could not see
a screenshot clearly, say which one rather than guessing.

## Checks (per screenshot)
1. Spacing: any elements touching, uneven gaps between siblings, uneven padding between similar cards or rows.
2. Alignment: edges that should line up but don't; icons not centered with their text; mixed button heights in a row.
3. Hierarchy: is there one obvious primary action per view? Do headings, labels, and body text look clearly different?
4. Truncation and overflow: cut-off text, content hitting edges, wasted empty regions, stray scrollbars.
5. Consistency: same component styled differently on this screen versus the others.
6. States: does the screen show a sensible empty, loading, error, or disabled state where it should?
7. Copy: raw ids, hashes, JSON, enum keys, inconsistent naming, placeholder text.
8. Contrast and legibility: text that is hard to read, tiny text, low-contrast icons.

## After the review
The builder fixes every P0 and P1, reruns `qa-ui.mjs`, and regenerates the
screenshots. P2 items are fixed if cheap or logged as follow-ups. Do not argue
with a finding without re-measuring it.
