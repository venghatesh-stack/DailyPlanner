/* Day Sheet "Scan paper sheet": the line parser. No AI; this decides
 * where each line of a handwritten page goes before the user reviews it. */
const { parse, timeOf } = require("../../static/js/day_sheet_scan.js");
let pass = 0, fail = 0;
const ok = (n, c) => { c ? pass++ : fail++; console.log((c ? "PASS " : "FAIL ") + n); };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const page = `Top 3
1. Finish promo doc
2) Review Q4 design
[x] Hiring sync prep
To-do:
[ ] Call vendor
- Book cab
x Pay electricity bill
|
Schedule
9 Standup
2pm 1:1 with Arun
14:30 Design review
Notes
Infra cost up 8% at 9.30 meeting`;
const r = parse(page, { method: "top3" });
ok("top 3 lines go to Top 3, numbering stripped",
   eq(r.slice(0, 3).map(x => [x.text, x.dest, x.done]),
      [["Finish promo doc", "top3", false], ["Review Q4 design", "top3", false], ["Hiring sync prep", "top3", true]]));
ok("to-dos with boxes, dashes and x", eq(r.slice(3, 6).map(x => [x.text, x.dest, x.done]),
   [["Call vendor", "todo", false], ["Book cab", "todo", false], ["Pay electricity bill", "todo", true]]));
ok("noise line dropped", !r.some(x => x.text === "|"));
ok("schedule: bare hour, pm and 24h", eq(r.slice(6, 9).map(x => [x.dest, x.text]),
   [["hour:09", "Standup"], ["hour:14", "1:1 with Arun"], ["hour:14", "14:30 Design review"]]));
ok("notes keep times as text", r[9].dest === "notes" && r[9].text.startsWith("Infra cost"));
ok("nothing else", r.length === 10);

const plain = "Write promo doc\nReview design\n1:1 prep\nHiring sync\nCall mom\n10:30am dentist";
const t3 = parse(plain, { method: "top3" });
ok("no headings, Top 3 method: first 3 to Top 3, rest To-do, times to schedule",
   eq(t3.map(x => x.dest), ["top3", "top3", "top3", "todo", "todo", "hour:10"]));
ok("10:30am keeps its minutes", t3[5].text === "10:30 dentist");
const ivy = parse(plain, { method: "ivylee" });
ok("Ivy Lee: lines fill the six", ivy.slice(0, 5).every(x => x.dest === "list:ivy"));
const one35 = parse("a big one\nmed one\nmed two\nmed three\nsmall one\nsmall two", { method: "135" });
ok("1-3-5 fills big, medium, small in order",
   eq(one35.map(x => x.dest), ["list:big", "list:medium", "list:medium", "list:medium", "list:small", "list:small"]));

const eis = parse("Do\nFile taxes\nSchedule\nGym plan\nDelegate\nExpense report\nDrop\nRandom meeting", { method: "eisenhower" });
ok("Eisenhower headings, Schedule is a quadrant there",
   eq(eis.map(x => x.dest), ["list:q_do", "list:q_plan", "list:q_delegate", "list:q_drop"]));
ok("'Do taxes' style line is not a heading", parse("Do taxes", { method: "eisenhower" })[0].text === "Do taxes");

const bujo = parse("• Call vendor\no Ops review\n- infra cost up\nx Sent invoice", { method: "bujo" });
ok("bullet journal kinds", eq(bujo.map(x => [x.kind, x.done]), [["task", false], ["event", false], ["note", false], ["task", true]]));

const mgr = parse("People\nFollow up with Priya on hiring\nQuick wins\nApprove leave", { method: "manager" });
ok("manager lists", eq(mgr.map(x => x.dest), ["list:people", "list:quick"]));
ok("numbered list is not a time", timeOf("3. Call bank", false) === null && timeOf("3 pm Call bank", false).hour === "15");
ok("12 am is midnight, bad minutes rejected", timeOf("12am backup", false).hour === "00" && timeOf("9:75 x yz", false) === null);
// What Tesseract really produced from a handwriting-font test page.
const ocr = parse("Top 3\n1. Finich promo doc\nTo-do\n[7 Bock cab for Monday\n[x Pay bill\n(_) Ring bank\nSehedule\n9:30 Standup\nMasks", { method: "top3" });
ok("misread heading still a heading", ocr.find(x => x.text === "Standup" || x.text.endsWith("Standup")).dest === "hour:09"
   && !ocr.some(x => x.text === "Sehedule"));
ok("misread boxes stripped", eq(ocr.filter(x => x.dest === "todo").slice(0, 3).map(x => [x.text, x.done]),
   [["Bock cab for Monday", false], ["Pay bill", true], ["Ring bank", false]]));
ok("short words are not fuzzy headings", ocr[ocr.length - 1].text === "Masks");
ok("empty input", eq(parse("", {}), []));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
