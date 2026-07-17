"use strict";

const state = { session: null, index: 0, listened: false, started: false, saving: false };

const $ = (id) => document.getElementById(id);
const elements = {
  profileLabel: $("profile-label"),
  profileMeta: $("profile-meta"),
  reviewerId: $("reviewer-id"),
  progressBar: $("progress-bar"),
  progressText: $("progress-text"),
  countPass: $("count-pass"),
  countFail: $("count-fail"),
  countPending: $("count-pending"),
  itemPosition: $("item-position"),
  clipId: $("clip-id"),
  currentState: $("current-state"),
  referenceText: $("reference-text"),
  binding: $("binding"),
  audio: $("audio"),
  listenHint: $("listen-hint"),
  listenedButton: $("listened-button"),
  note: $("note"),
  failButton: $("fail-button"),
  passButton: $("pass-button"),
  previousButton: $("previous-button"),
  nextButton: $("next-button"),
  nextOpenButton: $("next-open-button"),
  message: $("message"),
};

function reviewerValid() {
  return /^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$/.test(elements.reviewerId.value.trim());
}

function updateDecisionButtons() {
  const enabled = state.listened && reviewerValid() && !state.saving;
  elements.passButton.disabled = !enabled;
  elements.failButton.disabled = !enabled;
  elements.listenedButton.disabled = state.listened || !state.started || state.saving;
}

function render() {
  const session = state.session;
  const item = session.items[state.index];
  const summary = session.summary;
  const reviewed = summary.pass + summary.fail;
  elements.profileLabel.textContent = session.profile.label;
  elements.profileMeta.textContent = `${session.profile.group} · ${session.profile.split} · Manifest ${session.profile.source_manifest_sha256.slice(0, 12)}…`;
  elements.progressBar.style.width = `${(reviewed / summary.total) * 100}%`;
  elements.progressText.textContent = `${reviewed} von ${summary.total} geprüft`;
  elements.countPass.textContent = summary.pass;
  elements.countFail.textContent = summary.fail;
  elements.countPending.textContent = summary.pending;
  elements.itemPosition.textContent = `Clip ${state.index + 1} von ${summary.total}`;
  elements.clipId.textContent = item.clip_id;
  elements.referenceText.textContent = item.reference_text;
  elements.binding.textContent = `Clipbindung ${item.binding_short}…`;
  elements.currentState.textContent = item.decision || "OFFEN";
  elements.currentState.className = `state ${(item.decision || "pending").toLowerCase()}`;
  elements.note.value = item.note || "";
  elements.audio.src = item.audio_url;
  elements.audio.load();
  state.listened = false;
  state.started = false;
  elements.listenHint.textContent = "Audio vollständig abspielen. Falls der Browser das Ende nicht erkennt, danach die Bestätigung anklicken.";
  elements.previousButton.disabled = state.index === 0;
  elements.nextButton.disabled = state.index === session.items.length - 1;
  elements.message.textContent = item.decision
    ? `Zuletzt ${item.decision} durch ${item.reviewer_id} am ${item.reviewed_at_utc}. Eine neue Entscheidung wird zusätzlich protokolliert.`
    : "Noch keine Entscheidung protokolliert.";
  updateDecisionButtons();
}

async function loadSession() {
  const response = await fetch("/api/session", { cache: "no-store" });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Review konnte nicht geladen werden");
  state.session = body;
  state.index = Math.min(state.index, body.items.length - 1);
  render();
}

async function saveDecision(decision) {
  if (!state.listened) return;
  const reviewerId = elements.reviewerId.value.trim();
  const note = elements.note.value.trim();
  if (!reviewerValid()) {
    elements.message.textContent = "Bitte eine gültige Reviewerkennung eintragen.";
    return;
  }
  if (decision === "FAIL" && !note) {
    elements.message.textContent = "Für FAIL ist eine konkrete Notiz erforderlich.";
    elements.note.focus();
    return;
  }
  state.saving = true;
  updateDecisionButtons();
  elements.message.textContent = "Entscheidung wird hashgebunden protokolliert …";
  try {
    const response = await fetch("/api/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index: state.index, decision, note, reviewer_id: reviewerId }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Entscheidung konnte nicht gespeichert werden");
    state.session = body.session;
    const nextOpen = state.session.items.findIndex((item, index) => index > state.index && !item.decision);
    if (nextOpen >= 0) state.index = nextOpen;
    render();
  } catch (error) {
    elements.message.textContent = error.message;
  } finally {
    state.saving = false;
    updateDecisionButtons();
  }
}

elements.audio.addEventListener("ended", () => {
  state.listened = true;
  elements.listenHint.textContent = "Wiedergabe vollständig beendet. Jetzt Audio und Referenz bewusst vergleichen.";
  updateDecisionButtons();
});
elements.audio.addEventListener("play", () => {
  state.started = true;
  updateDecisionButtons();
});
elements.listenedButton.addEventListener("click", () => {
  if (!state.started || state.saving) return;
  state.listened = true;
  elements.listenHint.textContent = "Manuell als vollständig angehört bestätigt. Jetzt Audio und Referenz bewusst vergleichen.";
  updateDecisionButtons();
});
elements.reviewerId.addEventListener("input", () => {
  localStorage.setItem("transcom-reviewer-id", elements.reviewerId.value);
  updateDecisionButtons();
});
elements.passButton.addEventListener("click", () => saveDecision("PASS"));
elements.failButton.addEventListener("click", () => saveDecision("FAIL"));
elements.previousButton.addEventListener("click", () => { state.index -= 1; render(); });
elements.nextButton.addEventListener("click", () => { state.index += 1; render(); });
elements.nextOpenButton.addEventListener("click", () => {
  const open = state.session.items.findIndex((item) => !item.decision);
  if (open >= 0) {
    state.index = open;
    render();
  } else {
    elements.message.textContent = "Keine offenen Clips. FAIL-Entscheidungen müssen nach Behebung erneut manuell geprüft werden.";
  }
});

elements.reviewerId.value = localStorage.getItem("transcom-reviewer-id") || "";
loadSession().catch((error) => { elements.message.textContent = error.message; });
