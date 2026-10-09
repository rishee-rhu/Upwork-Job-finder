/* ---------------- dates ---------------- */
const UNIT_H = { second: 1 / 3600, minute: 1 / 60, min: 1 / 60, hour: 1, hr: 1, day: 24, week: 168, month: 730, quarter: 2190, year: 8760 };
function parseRelative(s, at = Date.now()) {
  const low = String(s).toLowerCase();
  if (/just now|moments ago/.test(low)) return at;
  if (low.includes("yesterday")) return at - 24 * 3600e3;
  for (const [w, d] of [["last week", 7], ["last month", 30], ["last quarter", 91]]) if (low.includes(w)) return at - d * 24 * 3600e3;
  const m = low.match(/(\d+|an?|one)\s*(second|minute|min|hour|hr|day|week|month|quarter|year)s?\s*ago/);
  if (!m) return null;
  const n = /^(a|an|one)$/.test(m[1]) ? 1 : +m[1];
  return at - n * UNIT_H[m[2]] * 3600e3;
}
function parseDate(v) {
  if (v == null || v === "") return null;
  if (typeof v === "number") return v > 1e12 ? v : v * 1000;
  const t = Date.parse(v);
  return isNaN(t) ? parseRelative(v) : t;
}

/* ---------------- normalize Apify items ---------------- */
function first(o, ...keys) {
  for (const k of keys) { let c = o; for (const p of k.split(".")) { c = c && typeof c === "object" ? c[p] : undefined; if (c == null) break; } if (c != null && c !== "" && !(Array.isArray(c) && !c.length)) return c; }
  return undefined;
}
function num(v) {
  if (v == null) return null; if (typeof v === "number") return v;
  const m = String(v).replace(/,/g, "").match(/([\d.]+)\s*([kKmM])?/); if (!m) return null;
  return +m[1] * (m[2] ? (m[2].toLowerCase() === "k" ? 1e3 : 1e6) : 1);
}
function bool(v) { if (v == null) return null; if (typeof v === "boolean") return v; return /^(true|yes|1|verified)$/i.test(String(v).trim()); }
function jobId(url) { const m = String(url || "").match(/~0?([0-9a-z]{6,})/i); return m ? m[1].toLowerCase() : null; }
function normalize(r, source, observedAt) {
  for (const k of ["job", "jobDetails", "node", "data", "item"]) if (r[k] && typeof r[k] === "object" && !Array.isArray(r[k])) r = { ...r[k], ...r };
  let url = first(r, "url", "link", "jobUrl", "job_url", "jobLink", "href");
  if (!url) { const cipher = first(r, "ciphertext", "cipherText", "jobCiphertext", "uid"); if (cipher && /^~/.test(cipher)) url = "https://www.upwork.com/jobs/" + cipher; }
  if (!url) return null;
  if (url.startsWith("/")) url = "https://www.upwork.com" + url;
  let hmin = num(first(r, "hourlyMin", "hourly_min", "hourlyBudgetMin", "hourly.min", "budget.hourlyMin", "hourlyBudget.min"));
  let hmax = num(first(r, "hourlyMax", "hourly_max", "hourlyBudgetMax", "hourly.max", "budget.hourlyMax", "hourlyBudget.max"));
  const hourly = first(r, "hourlyRate", "hourly_rate", "hourlyRange");
  if (hourly && !(hmin || hmax)) { const ns = (String(hourly).replace(/,/g, "").match(/[\d.]+/g) || []).map(Number); if (ns.length) { hmin = ns[0]; hmax = ns[ns.length - 1]; } }
  const budget = num(first(r, "budget.amount", "fixedPrice", "fixed_price", "amount.amount", "budget", "amount"));
  const jt = String(first(r, "jobType", "job_type", "type", "paymentType") || "").toLowerCase();
  if (jt.includes("hour") && !(hmin || hmax) && typeof r.budget === "string") { const ns = (r.budget.replace(/,/g, "").match(/[\d.]+/g) || []).map(Number); if (ns.length) { hmin = ns[0]; hmax = ns[ns.length - 1]; } }
  const type = jt.includes("hour") || hmin || hmax ? "hourly" : (jt.includes("fix") || budget ? "fixed" : null);
  let skills = first(r, "skills", "tags", "attrs") || [];
  if (typeof skills === "string") skills = skills.split(",").map(s => s.trim()).filter(Boolean);
  skills = skills.map(s => typeof s === "string" ? s : String(first(s, "name", "prettyName", "prefLabel") || ""));
  let locs = first(r, "allowedApplicantCountries", "allowedLocations", "allowed_locations", "preferredLocations", "locations") || [];
  if (typeof locs === "string") locs = locs.split(",").map(s => s.trim()).filter(Boolean);
  const scraped = parseDate(first(r, "scrapedAt", "scraped_at", "crawledAt", "fetchedAt"));
  return {
    url, id: jobId(url) || url.split("?")[0],
    title: String(first(r, "title", "jobTitle", "name") || ""),
    description: String(first(r, "description", "snippet", "body", "jobDescription") || ""),
    postedAt: parseDate(first(r, "absoluteDate", "posted_at", "postedAt", "publishedOn", "publishedAt", "createdOn", "createdAt", "date", "postedOn", "posted", "publishTime",
      "publishedDate", "postedDate", "datePosted", "date_posted", "createdDateTime", "postedTime", "posted_on", "absoluteDate", "time", "renewedOn", "createTime")),
    type, hmin, hmax, budget: type === "fixed" ? budget : null, skills, locs,
    client: {
      country: first(r, "clientLocation", "client.country", "clientCountry", "client_country", "client.location.country", "buyer.location.country", "country"),
      verified: bool(first(r, "client.paymentVerified", "paymentVerified", "payment_verified", "client.payment_verified", "buyer.isPaymentMethodVerified", "client.isPaymentVerified")),
      spent: num(first(r, "client.totalSpent", "clientTotalSpent", "total_spent", "client.total_spent", "buyer.stats.totalCharges.amount", "client.spent")),
      hireRate: num(first(r, "clientHireRatePercent", "client.hireRate", "hireRate", "hire_rate", "client.hire_rate")),
      hires: num(first(r, "client.hires", "clientHires", "client.totalHires", "buyer.stats.totalJobsWithHires")),
      posted: num(first(r, "client.jobsPosted", "jobsPosted", "client.jobs_posted", "client.totalJobs", "buyer.jobs.postedCount")),
      rating: num(first(r, "client.rating", "clientRating", "client.feedback", "buyer.stats.score")),
      reviews: num(first(r, "client.reviews", "clientReviews", "client.reviewsCount", "buyer.stats.feedbackCount")),
    },
    act: {
      proposals: num(first(r, "proposals", "proposalsCount", "totalApplicants", "applicants", "activity.proposals", "proposalsTier")),
      interviewing: num(first(r, "interviewing", "activity.interviewing", "totalInterviewing")),
      invites: num(first(r, "invitesSent", "invites_sent", "activity.invitesSent")),
      hires: num(first(r, "hires", "activity.hires", "totalHired")) ?? (r.hasHired === true ? 1 : null),
      needed: num(first(r, "freelancersNeeded", "freelancers_needed", "activity.freelancersNeeded", "numberOfPositionsToHire")),
    },
    closedFlag: bool(first(r, "isPrivate", "private", "isClosed", "closed")) || /closed|private|cancel/i.test(String(first(r, "status", "jobStatus") || "")),
    source, observedAt, scrapedAt: scraped,
  };
}
function compensation(j) {
  if (j.type === "hourly" && (j.hmin || j.hmax)) return j.hmin && j.hmax && j.hmin !== j.hmax ? `$${j.hmin}-$${j.hmax}/hr` : `$${j.hmin || j.hmax}/hr`;
  if (j.budget) return `$${Math.round(j.budget).toLocaleString()} fixed`;
  return j.type || "not stated";
}

/* ---------------- gates & scoring (mirror of findjobs/gates.py) ---------------- */
class Excl { constructor(gate, reason) { this.gate = gate; this.reason = reason; } }
const ageH = (j, at) => j.postedAt ? (at - j.postedAt) / 3600e3 : null;
const COUNTRY = { us: "united states", "u.s.": "united states", usa: "united states", uk: "united kingdom", "u.k.": "united kingdom", england: "united kingdom", uae: "united arab emirates" };
const REGIONS = { asia: ["india", "pakistan", "bangladesh", "philippines", "indonesia", "vietnam", "sri lanka", "nepal", "malaysia", "thailand"], europe: ["united kingdom", "germany", "france", "spain", "italy", "netherlands", "poland", "ireland", "portugal"], americas: ["united states", "canada", "mexico", "brazil", "argentina", "colombia"] };
const ctry = s => { s = String(s).trim().toLowerCase().replace(/\.$/, ""); return COUNTRY[s] || s; };

function gateAvailability(j, at) {
  if (j.closedFlag) throw new Excl("availability", "marked private or closed in the scrape");
  if (j.source === "live") return;
  if (j.scrapedAt && at - j.scrapedAt <= 60 * 60e3) return;
  throw new Excl("availability", j.scrapedAt ? `scraped ${Math.round((at - j.scrapedAt) / 60e3)} min ago, too old to trust` : "file has no scrape time; can't confirm it's open");
}
function gateFreshness(j, at) {
  const h = ageH(j, at);
  if (h == null) { if (j.source === "live") return; throw new Excl("freshness", "posted time unknown"); }
  if (h <= 72) return;
  if (h > 24 * 14) throw new Excl("freshness", `posted ${Math.round(h / 24)} days ago`);
  const strong = j.act.proposals != null && j.act.proposals < 5 && (j.act.needed || 1) > 1;
  if (!strong) throw new Excl("freshness", `posted ${(h / 24).toFixed(1)} days ago`);
}
function gateLocation(j, p) {
  if (!j.locs.length) return;
  const me = ctry(p.country || ""), allowed = j.locs.map(ctry);
  if (allowed.includes("worldwide") || allowed.includes(me) || allowed.some(a => (REGIONS[a] || []).includes(me))) return;
  throw new Excl("eligibility", "location restricted to " + j.locs.join(", "));
}
function gateCompetition(j) {
  const a = j.act;
  if (a.hires && (a.needed || 1) <= a.hires) throw new Excl("competition", "already hired");
  if ((a.proposals || 0) >= 50 && (a.interviewing || 0) >= 5) throw new Excl("competition", `${a.proposals}+ proposals, ${a.interviewing} interviewing`);
}
function commissionPre(j, p) {
  const t = j.title + "\n" + j.description;
  const pure = /(commission[- ]only|100\s*%\s*commission|no (base|fixed|hourly) (pay|salary|rate)|pure(ly)? commission|only commission)/i.test(t);
  const vague = /unlimited earning|uncapped earning|earn as much as you want|unlimited income/i.test(t);
  if (!/commission/i.test(t) && !vague) return null;
  if (!p.allow_commission && pure) throw new Excl("commission", "pure commission; profile doesn't accept commission");
  if (vague && !/(\d+\s*%|\$\s*\d+)/.test(t)) throw new Excl("commission", "vague 'unlimited earnings' with no defined commission");
  return pure ? "pure" : "has";
}
function clientPts(j) {
  const c = j.client;
  if ([c.verified, c.spent, c.hireRate, c.rating].every(v => v == null)) return [5, "client data missing"];
  let p = 0; const n = [];
  if (c.verified) { p += 3; n.push("payment verified"); } else if (c.verified === false) n.push("payment NOT verified");
  if (c.spent != null) { p += c.spent >= 1e4 ? 3 : c.spent >= 1e3 ? 2 : c.spent > 0 ? 1 : 0; n.push(`$${Math.round(c.spent).toLocaleString()} spent`); }
  if (c.hireRate != null) { p += c.hireRate >= 50 ? 3 : c.hireRate >= 20 ? 1.5 : 0; n.push(`${Math.round(c.hireRate)}% hire rate`); }
  if (c.rating != null && (c.reviews || 0) >= 1) { p += c.rating >= 4.5 ? 2 : c.rating >= 4 ? 1 : 0; n.push(`${c.rating.toFixed(1)}★`); }
  if ((c.posted || 0) >= 5 && !c.hires && !c.spent) { p -= 3; n.push(`${c.posted} posts, no hires`); } else p += 1;
  return [Math.max(0, Math.min(12, p)), n.join(", ")];
}
function compPts(j) {
  const a = j.act;
  if (a.proposals == null && a.interviewing == null) return [5, "activity unknown"];
  let p = 0; const n = [];
  if (a.proposals != null) { const x = a.proposals; p += x < 5 ? 6 : x < 10 ? 5 : x < 20 ? 3.5 : x < 50 ? 2 : 0; n.push(`${x}${x >= 50 ? "+" : ""} proposals`); } else p += 3;
  if (a.interviewing != null) { const i = a.interviewing; p += i === 0 ? 4 : i <= 2 ? 3 : i <= 5 ? 1.5 : 0; n.push(`${i} interviewing`); } else p += 2;
  if (a.invites != null) { p += a.invites <= 5 ? 1 : 0; n.push(`${a.invites} invites`); }
  return [Math.max(0, Math.min(12, p)), n.join(", ")];
}
const freshPts = (j, at) => { const h = ageH(j, at); return h == null ? 0 : h <= 6 ? 5 : h <= 24 ? 4 : h <= 72 ? 2 : 1; };
function commercialPts(j, cc) {
  if (j.type === "hourly" && j.hmax) return j.hmax >= 15 ? 3 : j.hmax >= 8 ? 2 : 1;
  if (j.type === "fixed" && j.budget) return j.budget >= 300 ? 3 : j.budget >= 100 ? 2 : 1;
  return cc === "pure" ? 0.5 : 1.5;
}
function profilePts(p) {
  const u = p.upwork; if (!u || (u.job_success_score == null && u.completed_jobs == null)) return 5;
  let s = 0;
  if (u.job_success_score != null) s += u.job_success_score >= 90 ? 4 : u.job_success_score >= 80 ? 3 : 1;
  if (u.completed_jobs != null) s += u.completed_jobs >= 10 ? 3 : u.completed_jobs >= 3 ? 2 : u.completed_jobs >= 1 ? 1 : 0;
  if (u.rating != null) s += u.rating >= 4.8 ? 2 : u.rating >= 4.5 ? 1 : 0;
  if ((u.badges || []).length) s += 1;
  return Math.min(10, s);
}
const COMM_ADJ = { none: 0, paid_plus_commission: 0, base_plus_commission: 0, meeting_fee_plus_commission: -2, pure_commission_client_leads: -6, pure_commission_self_sourced: -15 };

/* Evidence grounding: every fact Claude cites must actually appear in the profile. */
const words = s => new Set(String(s).toLowerCase().match(/[a-z0-9]{3,}/g) || []);
function grounded(item, facts) {
  const w = words(item); if (!w.size) return false;
  return facts.some(f => { const fw = words(f); let hit = 0; for (const x of w) if (fw.has(x)) hit++; return hit / w.size >= 0.5; });
}

/* ---------------- Claude judge ---------------- */
const CLAMP = { direct_match: 20, evidence_match: 20, differentiation: 12, requirement_gaps: 6 };
function judgePrompt(p, jobs) {
  return `You screen Upwork jobs for one freelancer. Precision beats volume: a wrong recommendation wastes their Connects and credibility.
Rules:
- A requirement counts as matched only if the profile's evidence proves it. Never invent case studies, tools, results or experience.
- hard_eligible=false when the job has a mandatory requirement the freelancer clearly fails (location, timezone/hours, language level, certification, exact years, mandatory recent case studies or portfolio, required tool expertise).
- Shared buzzwords aren't fit. Score direct_match on the core work.
- differentiation rewards intersections where the freelancer has uncommon proof. Generic work scores low.
- proposal_feasible=true only if a persuasive 2-3 sentence opener can be written from real evidence without exaggeration. Write it in proposal_opener in first person as the freelancer; if infeasible, say why there.
- dossier_evidence: quote the profile facts you relied on, close to their original wording.

PROFILE:
${JSON.stringify(p)}

JOBS:
${JSON.stringify(jobs.map(j => ({ id: j.id, title: j.title, description: j.description.slice(0, 2500), skills: j.skills.slice(0, 15), pay: compensation(j), allowed_locations: j.locs, client_country: j.client.country })))}

Reply with only a JSON array, one object per job, in this shape:
[{"id": str, "hard_eligible": bool, "failed_requirements": [str], "direct_match": 0-20, "evidence_match": 0-20, "differentiation": 0-12, "requirement_gaps": 0-6 (6 = no gaps), "capability_fit": "High"|"Medium"|"Low", "evidence_fit": "High"|"Medium"|"Low", "commission_structure": "none"|"paid_plus_commission"|"base_plus_commission"|"meeting_fee_plus_commission"|"pure_commission_client_leads"|"pure_commission_self_sourced"|"vague_commission", "proposal_feasible": bool, "proposal_opener": str, "why_selected": str, "dossier_evidence": [str], "risks": [str]}]`;
}
async function judgeAll(p, jobs, signal) {
  const out = {};
  for (let i = 0; i < jobs.length; i += 6) {
    const batch = jobs.slice(i, i + 6);
    log(`Claude: judging jobs ${i + 1}-${i + batch.length} of ${jobs.length}…`);
    const arr = await sample.json(judgePrompt(p, batch), { signal, modelTier: "default" });
    for (const r of Array.isArray(arr) ? arr : []) if (r && r.id != null) out[String(r.id)] = r;
  }
  return out;
}
function judgmentGate(jd, p) {
  if (!jd) throw new Excl("judgment", "Claude returned no judgment for this job");
  for (const [k, hi] of Object.entries(CLAMP)) jd[k] = Math.max(0, Math.min(hi, Math.round(+jd[k] || 0)));
  if (!jd.hard_eligible) throw new Excl("eligibility", (jd.failed_requirements || []).join("; ") || "fails a mandatory requirement");
  if (jd.capability_fit === "Low") throw new Excl("capability", "core work outside what the profile shows");
  if (jd.evidence_fit === "Low") throw new Excl("evidence", "fit can't be backed by the profile");
  if (jd.commission_structure === "vague_commission") throw new Excl("commission", "undefined commission");
  if (!jd.proposal_feasible) throw new Excl("proposal", "no honest opener possible: " + String(jd.proposal_opener || "").slice(0, 140));
  const facts = [...(p.evidence || []), ...(p.strengths || []), ...(p.domains || []), ...(p.differentiators || [])];
  const cited = (jd.dossier_evidence || []).filter(x => grounded(x, facts));
  if (!cited.length) throw new Excl("evidence", "the facts Claude cited aren't in the profile");
  jd.dossier_evidence = cited;
}
function score(j, jd, p, at, cc) {
  const [cp, cn] = clientPts(j), [mp, mn] = compPts(j);
  const parts = { direct: jd.direct_match, evidence: jd.evidence_match, diff: jd.differentiation, client: cp, competition: mp, profile: profilePts(p), gaps: jd.requirement_gaps, fresh: freshPts(j, at), commercial: commercialPts(j, cc), commission: COMM_ADJ[jd.commission_structure] || 0 };
  const total = Math.max(0, Math.min(100, Object.values(parts).reduce((a, b) => a + b, 0)));
  const pure = /^pure_commission/.test(jd.commission_structure);
  const h = ageH(j, at) ?? 999;
  let verdict = total >= 75 && h <= 24 && !pure ? "APPLY NOW" : total >= 62 ? "APPLY" : total >= 50 ? "REVIEW" : "";
  if (pure && verdict) verdict = "REVIEW";
  return { job: j, jd, parts, total: Math.round(total), verdict, clientNote: cn, compNote: mn };
}

/* ---------------- Apify via connector ---------------- */
const descCache = {};
async function schemaProps(tool) {
  if (!(tool in descCache)) {
    try { const d = await mcp.describeTool(APIFY, tool); descCache[tool] = d?.inputSchema?.properties || {}; }
    catch { descCache[tool] = null; }
  }
  return descCache[tool];
}
function pickKey(props, patterns, fallback) {
  if (!props) return fallback;
  const keys = Object.keys(props);
  for (const re of patterns) { const k = keys.find(x => re.test(x)); if (k) return k; }
  return fallback;
}
function findDeep(obj, re, depth = 0) {
  if (!obj || typeof obj !== "object" || depth > 5) return undefined;
  for (const [k, v] of Object.entries(obj)) if (re.test(k) && (typeof v === "string" || typeof v === "number")) return v;
  for (const v of Object.values(obj)) { const r = findDeep(v, re, depth + 1); if (r !== undefined) return r; }
  return undefined;
}
/* An object that looks like a run: has both an id and a status. */
function findRun(obj, depth = 0) {
  if (!obj || typeof obj !== "object" || depth > 5) return null;
  if (!Array.isArray(obj) && obj.status && (obj.id || obj.runId)) return obj;
  for (const v of Object.values(obj)) { const r = findRun(v, depth + 1); if (r) return r; }
  return null;
}
/* Apify's MCP tools often answer in text (markdown with JSON inside), not structured JSON. */
function parseLoose(t) {
  if (typeof t !== "string") return t;
  try { return JSON.parse(t); } catch {}
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) { try { return JSON.parse(fence[1]); } catch {} }
  for (const [o, c] of [["[", "]"], ["{", "}"]]) { const a = t.indexOf(o), b = t.lastIndexOf(c); if (a >= 0 && b > a) { try { return JSON.parse(t.slice(a, b + 1)); } catch {} } }
  return null;
}
function textOf(res) { return (res?.content || []).filter(b => b.type === "text").map(b => b.text).join("\n"); }
function payloadOf(res) {
  if (res?.structuredContent && typeof res.structuredContent === "object") return res.structuredContent;
  const p = res?.payload;
  if (p && typeof p === "object") return p;
  return parseLoose(typeof p === "string" ? p : textOf(res)) ?? {};
}
function fromText(res, kind) {
  const t = textOf(res) || (typeof res?.payload === "string" ? res.payload : "");
  const re = { dataset: /(?:default)?\s*dataset[\s_-]*id["'`*:\s=]+([A-Za-z0-9]{10,})/i, run: /run[\s_-]*id["'`*:\s=]+([A-Za-z0-9]{10,})/i,
    status: /\b(SUCCEEDED|RUNNING|READY|FAILED|ABORTED|TIMED-OUT|TIMING-OUT)\b/ }[kind];
  const m = t.match(re); return m ? m[1] : undefined;
}
function itemsOf(payload, depth = 0) {
  if (typeof payload === "string") payload = parseLoose(payload);
  if (Array.isArray(payload)) return payload.filter(x => x && typeof x === "object");
  if (!payload || typeof payload !== "object" || depth > 3) return [];
  for (const k of ["items", "data", "results", "datasetItems", "records"]) { const v = itemsOf(payload[k], depth + 1); if (v.length) return v; }
  return [];
}
const sleep = (ms, signal) => new Promise((res, rej) => { const t = setTimeout(res, ms); signal?.addEventListener("abort", () => { clearTimeout(t); rej({ code: "cancelled" }); }, { once: true }); });
const snip = (v, n = 1500) => { const s = typeof v === "string" ? v : JSON.stringify(v); return s && s.length > n ? s.slice(0, n) + "…" : s; };
let DIAG = null;

async function runQuery(q, actor, tpl, limit, signal) {
  const d = { query: q, steps: [] }; DIAG.queries.push(d);
  const callProps = await schemaProps("call-actor");
  d.schemas = { "call-actor": callProps ? Object.keys(callProps) : "unavailable" };
  const input = JSON.parse(tpl.replaceAll("{qurl}", encodeURIComponent('"' + q + '"')).replaceAll("{query}", q.replace(/"/g, '\\"')).replace(/"\{limit\}"/g, String(limit)));
  const args = {};
  args[pickKey(callProps, [/^actor$/i, /actor(id|name)?$/i], "actor")] = actor;
  args[pickKey(callProps, [/^input$/i, /input/i], "input")] = input;
  if (callProps && "waitSecs" in callProps) args.waitSecs = 45;
  if (callProps && "callOptions" in callProps) args.callOptions = { maxItems: limit };
  d.args = args;
  const res = await mcp.callTool(APIFY, "call-actor", args, { cache: false, signal });
  const pay = payloadOf(res);
  d.steps.push({ tool: "call-actor", reply: snip(textOf(res) || res.payload) });
  const run = findRun(pay);
  let status = String(run?.status || findDeep(pay, /^status$/i) || fromText(res, "status") || "");
  const runId = findDeep(pay, /^(runId|run_id|actorRunId)$/i) ?? run?.id ?? fromText(res, "run");
  let datasetId = findDeep(pay, /^(datasetId|defaultDatasetId|dataset_id)$/i) ?? fromText(res, "dataset");
  const inline = itemsOf(pay);
  Object.assign(d, { status, runId, datasetId, inlineItems: inline.length });
  if (inline.length && (!datasetId || /SUCCEEDED/i.test(status))) return inline;
  for (let i = 0; i < 24 && !/SUCCEEDED|FAILED|ABORTED|TIMED-OUT/i.test(status) && runId; i++) {
    await sleep(5000, signal);
    const rp = await schemaProps("get-actor-run");
    const ra = {}; ra[pickKey(rp, [/^runId$/i, /run/i, /^id$/i], "runId")] = runId;
    const rr = await mcp.callTool(APIFY, "get-actor-run", ra, { cache: false, signal });
    const r = payloadOf(rr);
    status = String(findRun(r)?.status || findDeep(r, /^status$/i) || fromText(rr, "status") || status);
    datasetId = datasetId || findDeep(r, /^(datasetId|defaultDatasetId)$/i) || fromText(rr, "dataset");
    if (i === 0) d.steps.push({ tool: "get-actor-run", reply: snip(textOf(rr) || rr.payload, 800) });
    log(`  …run ${String(runId).slice(0, 8)} ${status || "running"}`);
  }
  d.status = status; d.datasetId = datasetId;
  if (/FAILED|ABORTED|TIMED-OUT/i.test(status)) throw { code: "tool_error", message: `Apify run ${status.toLowerCase()}. Check the actor ID and its input template.` };
  if (!datasetId) throw { code: "tool_error", message: "Apify's reply had no dataset ID. Copy the run details and send them to Claude." };
  const dp = await schemaProps("get-dataset-items");
  d.schemas["get-dataset-items"] = dp ? Object.keys(dp) : "unavailable";
  const da = {}; da[pickKey(dp, [/^datasetId$/i, /dataset/i], "datasetId")] = datasetId;
  if (!dp || "limit" in dp) da.limit = limit;
  const dr = await mcp.callTool(APIFY, "get-dataset-items", da, { cache: false, signal });
  const items = itemsOf(payloadOf(dr));
  d.steps.push({ tool: "get-dataset-items", items: items.length, reply: items.length ? undefined : snip(textOf(dr) || dr.payload) });
  if (items.length) { d.itemKeys = Object.keys(items[0]); d.firstItem = snip(items[0], 2500); }
  return items;
}

/* ---------------- pipeline ---------------- */
function parseFileRows(name, text) {
  if (/\.csv$/i.test(name)) {
    const rows = []; const lines = text.split(/\r?\n/).filter(Boolean);
    const split = l => { const out = []; let cur = "", q = false; for (let i = 0; i < l.length; i++) { const c = l[i]; if (c === '"') { if (q && l[i + 1] === '"') { cur += '"'; i++; } else q = !q; } else if (c === "," && !q) { out.push(cur); cur = ""; } else cur += c; } out.push(cur); return out; };
    const head = split(lines[0]);
    for (const l of lines.slice(1)) { const v = split(l); rows.push(Object.fromEntries(head.map((h, i) => [h.trim(), v[i]]))); }
    return rows;
  }
  const d = JSON.parse(text); return Array.isArray(d) ? d : (d.items || d.jobs || []);
}

