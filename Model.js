// Pure presentation and parsing helpers shared by the bar widget, the panel,
// and the Node test suite. No Qt, no state: everything here is a function of
// its arguments so it can be unit-tested outside the shell.

function defaultResponse() {
  return { ok: false, error: "No response", items: [], dependencies: {} }
}

function parseResponse(raw) {
  try {
    var parsed = JSON.parse(String(raw || ""))
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return defaultResponse()
    if (!Array.isArray(parsed.items)) parsed.items = []
    if (!parsed.dependencies || typeof parsed.dependencies !== "object") parsed.dependencies = {}
    return parsed
  } catch (error) {
    return defaultResponse()
  }
}

function filePath(url) {
  return decodeURIComponent(String(url || "").replace(/^file:\/\//, ""))
}

function bool(value, fallback) {
  if (value === undefined || value === null) return fallback === true
  if (typeof value === "boolean") return value
  return ["1", "true", "yes", "on"].indexOf(String(value).toLowerCase()) !== -1
}

function boundedInt(value, fallback, minimum, maximum) {
  var parsed = parseInt(String(value), 10)
  if (!isFinite(parsed)) parsed = fallback
  return Math.max(minimum, Math.min(maximum, parsed))
}

// ------------------------------------------------------------------ state

function statusLabel(status) {
  var state = String(status || "checking")
  if (state === "unlocked") return "Vault unlocked"
  if (state === "locked") return "Vault locked"
  if (state === "unauthenticated") return "Sign in required"
  if (state === "unavailable") return "Setup required"
  if (state === "error") return "Needs attention"
  return "Checking Bitwarden…"
}

function statusGlyph(status) {
  var state = String(status || "checking")
  if (state === "unlocked") return "󰌾"
  if (state === "locked") return "󰌿"
  if (state === "unauthenticated") return "󰌋"
  if (state === "unavailable") return "󰏔"
  if (state === "error") return "󰀪"
  return "󰑓"
}

function tooltip(service) {
  if (!service) return "Checking Bitwarden…"
  var label = statusLabel(service.vaultStatus)
  if (service.busy) return label + " · working…"
  if (service.lastError) return label + " · " + service.lastError
  return label
}

// Host shown for an account: the configured server when there is one, the
// server the CLI reports otherwise, and bitwarden.com when neither is set
// (the CLI reports null for the official cloud).
function serverLabel(configured, reported) {
  var url = String(configured || "").trim() || String(reported || "").trim()
  if (url === "") return "bitwarden.com"
  var host = itemHost(url)
  return host === "" ? url : host
}

// Copy for the gate — everything the panel shows before the vault is open.
// One object per state so the panel stays a thin view and the words can be
// tested.
function gateCopy(status, ready, missing, unlockPrompt) {
  var state = String(status || "checking")
  if (!ready && state !== "checking") {
    return {
      title: "Set up OmaWarden",
      body: "Some packages are missing. OmaWarden can install them in a terminal window.",
      action: "Install requirements",
      glyph: "󰏔",
      key: "u"
    }
  }
  if (state === "unauthenticated") {
    return {
      title: "Sign in to Bitwarden",
      body: "Sign-in happens in a terminal window so your email, master password and two-step code are typed straight into Bitwarden, never into the shell.",
      action: "Sign in",
      glyph: "󰌋",
      key: "u"
    }
  }
  if (state === "locked") {
    return {
      title: "Vault locked",
      body: String(unlockPrompt || "pinentry").toLowerCase() === "pinentry"
        ? "Unlock in a separate password window. Your unlocked session stays private to OmaWarden."
        : "Unlock in a native Omarchy prompt. Your password is cleared as soon as it is handed to Bitwarden.",
      action: "Unlock vault",
      glyph: "󰌿",
      key: "u"
    }
  }
  if (state === "checking") {
    return { title: "Checking Bitwarden…", body: "", action: "", glyph: "󰑓", key: "" }
  }
  return {
    title: "Needs attention",
    body: "OmaWarden couldn't read the vault. If Bitwarden lives somewhere unusual, set its command in Settings.",
    action: "Try again",
    glyph: "󰀪",
    key: "r"
  }
}

// The three-step path from a fresh install to an open vault. Each step is
// "done", "current", or "todo"; an empty list hides the strip (unknown or
// broken states have no honest position on it).
function setupSteps(status, ready) {
  var state = String(status || "checking")
  if (state === "checking" || state === "error") return []
  var position = !ready ? 0 : (state === "unauthenticated" ? 1 : (state === "locked" ? 2 : 3))
  var labels = ["Install", "Sign in", "Unlock"]
  var steps = []
  for (var index = 0; index < labels.length; index++) {
    steps.push({
      label: labels[index],
      state: index < position ? "done" : (index === position ? "current" : "todo")
    })
  }
  return steps
}

// One row per runtime requirement, with the package a user would install.
function requirementRows(dependencies, needPinentry) {
  var deps = dependencies || {}
  var rows = [
    { key: "bw", label: "Bitwarden CLI", detail: "bitwarden-cli", ok: deps.bw === true },
    { key: "wlCopy", label: "Secure clipboard", detail: "wl-clipboard", ok: deps.wlCopy === true }
  ]
  if (needPinentry === true)
    rows.splice(1, 0, { key: "pinentry", label: "Unlock prompt", detail: "pinentry", ok: deps.pinentry === true })
  return rows
}

// ------------------------------------------------------------------ items

function itemHost(url) {
  var host = String(url || "").replace(/^https?:\/\//, "").split("/")[0]
  return host.replace(/:\d+$/, "")
}

function isCard(item) {
  return !!item && Number(item.type) === 3
}

// Real vaults name a lot of entries after the site they belong to, so the
// host would repeat the title on every second row. Drop it when it carries
// nothing the name has not already said.
function hostEchoesName(name, host) {
  var title = String(name || "").toLowerCase().replace(/^\s+|\s+$/g, "")
  var domain = String(host || "").toLowerCase().replace(/^www\./, "")
  if (title === "" || domain === "") return false
  if (title === domain) return true
  if (title.replace(/\s+/g, "") === domain) return true
  return title === domain.split(".")[0]
}

function itemSubtitle(item, showUsernames) {
  if (!item) return ""
  var parts = []
  if (isCard(item)) {
    if (showUsernames && String(item.cardholder || "") !== "") parts.push(String(item.cardholder))
    if (String(item.brand || "") !== "") parts.push(String(item.brand))
    if (String(item.last4 || "") !== "") parts.push("•••• " + String(item.last4))
    return parts.join(" · ")
  }
  if (showUsernames && String(item.username || "") !== "") parts.push(String(item.username))
  if (String(item.url || "") !== "") {
    try {
      var host = itemHost(item.url)
      if (host !== "" && !hostEchoesName(item.name, host)) parts.push(host)
    } catch (error) {}
  }
  return parts.join(" · ")
}

// True for the first row of each initial in an alphabetically ordered list.
// The result rows use it to fade repeated monograms so a run of same-letter
// entries reads as one group instead of a column of identical tiles.
function isGroupStart(items, index) {
  if (!items || index <= 0) return true
  var previous = items[index - 1]
  var current = items[index]
  if (!previous || !current) return true
  return monogram(previous.name) !== monogram(current.name)
}

// Group label for a row while browsing (empty query). Searching returns a
// ranked list where groups would only get in the way, so it yields "".
function sectionLabel(item, browsing) {
  if (!browsing || !item) return ""
  if (item.recent === true) return "Recent"
  if (item.favorite === true) return "Favorites"
  return "All items"
}

function isSectionStart(items, index, browsing) {
  if (!browsing || !items || index < 0 || index >= items.length) return false
  if (index === 0) return true
  return sectionLabel(items[index], true) !== sectionLabel(items[index - 1], true)
}

function actionAvailable(item, action) {
  if (!item) return false
  if (action === "number") return isCard(item) && item.hasNumber === true
  if (action === "cardholder") return isCard(item) && item.hasCardholder === true
  if (action === "cardCode") return isCard(item) && item.hasCardCode === true
  if (action === "expiry") return isCard(item) && item.hasExpiry === true
  if (action === "password") return item.hasPassword === true
  if (action === "username") return String(item.username || "") !== ""
  if (action === "totp") return item.hasTotp === true
  if (action === "open") return String(item.url || "") !== ""
  return false
}

function itemActions(item) {
  return isCard(item)
    ? ["number", "cardholder", "cardCode", "expiry"]
    : ["password", "username", "totp", "open"]
}

function defaultAction(item, configured) {
  if (isCard(item)) {
    var cardActions = itemActions(item)
    for (var index = 0; index < cardActions.length; index++)
      if (actionAvailable(item, cardActions[index])) return cardActions[index]
    return ""
  }
  var preferred = String(configured || "Password").toLowerCase()
  if (preferred === "username" && actionAvailable(item, "username")) return "username"
  if (actionAvailable(item, "password")) return "password"
  if (actionAvailable(item, "username")) return "username"
  if (actionAvailable(item, "open")) return "open"
  if (actionAvailable(item, "totp")) return "totp"
  return ""
}

// The copy Enter performs, normalised from the "Enter copies" setting.
function primaryAction(configured, item) {
  if (isCard(item)) return defaultAction(item, configured)
  return String(configured || "Password").toLowerCase() === "username" ? "username" : "password"
}

// The copy Shift+Enter performs: whichever of password/username Enter does
// not already cover.
function alternateAction(configured, item) {
  if (isCard(item)) {
    var primary = primaryAction(configured, item)
    var cardActions = itemActions(item)
    for (var index = 1; index < cardActions.length; index++)
      if (cardActions[index] !== primary && actionAvailable(item, cardActions[index])) return cardActions[index]
    return ""
  }
  return String(configured || "Password").toLowerCase() === "username" ? "password" : "username"
}

function actionLabel(action) {
  if (action === "number") return "Card number"
  if (action === "cardholder") return "Cardholder"
  if (action === "cardCode") return "Security code"
  if (action === "expiry") return "Expiry"
  if (action === "password") return "Password"
  if (action === "username") return "Username"
  if (action === "totp") return "Code"
  if (action === "open") return "Website"
  return ""
}

function actionGlyph(action) {
  if (action === "number") return "󰄰"
  if (action === "cardholder") return "󰀄"
  if (action === "cardCode") return "󰌆"
  if (action === "expiry") return "󰃭"
  if (action === "password") return "󰌆"
  if (action === "username") return "󰀄"
  if (action === "totp") return "󰔛"
  if (action === "open") return "󰖟"
  return ""
}

function actionTooltip(action) {
  if (action === "number") return "Copy card number  ·  Ctrl+C"
  if (action === "cardholder") return "Copy cardholder  ·  Ctrl+B"
  if (action === "cardCode") return "Copy security code  ·  Ctrl+T"
  if (action === "expiry") return "Copy expiration date"
  if (action === "password") return "Copy password  ·  Ctrl+C"
  if (action === "username") return "Copy username  ·  Ctrl+B"
  if (action === "totp") return "Copy one-time code  ·  Ctrl+T"
  if (action === "open") return "Open website  ·  Ctrl+U"
  return ""
}

function unavailableActionTooltip(action) {
  if (action === "number") return "No number saved for this card"
  if (action === "cardholder") return "No cardholder saved for this card"
  if (action === "cardCode") return "No security code saved for this card"
  if (action === "expiry") return "No expiration date saved for this card"
  if (action === "password") return "No password saved for this login"
  if (action === "username") return "No username saved for this login"
  if (action === "totp") return "No authenticator key saved for this login"
  if (action === "open") return "No website saved for this login"
  return ""
}

// First letter of an entry name, used for the monogram tile in a result row.
// Skips ASCII punctuation and whitespace so "  [work] github" still reads W.
function monogram(name) {
  var text = String(name || "")
  for (var index = 0; index < text.length; index++) {
    var character = text.charAt(index)
    if (/[0-9A-Za-z]/.test(character)) return character.toUpperCase()
    if (character.charCodeAt(0) > 127) return character.toUpperCase()
  }
  return "•"
}

// ------------------------------------------------------------------ notices

// Text of the clipboard notice after a copy. `remaining` is whole seconds
// left before the agent clears the clipboard.
function copyNotice(field, remaining) {
  var noun = actionLabel(String(field || "password").toLowerCase()) || "Password"
  var seconds = Math.max(0, Math.ceil(Number(remaining) || 0))
  if (seconds <= 0) return noun + " copied · clipboard cleared"
  return noun + " copied · clears in " + seconds + " s"
}

// Human phrasing for the vault's last sync, shown under the panel title.
// Returns an empty string for anything unparsable so the caller can drop
// the clause entirely rather than print "Invalid Date".
function relativeSync(value, nowMs) {
  var raw = String(value || "").replace(/^\s+|\s+$/g, "")
  if (raw === "") return ""
  var parsed = Date.parse(raw)
  if (!isFinite(parsed)) return ""
  var now = isFinite(nowMs) ? nowMs : Date.now()
  var seconds = Math.max(0, Math.round((now - parsed) / 1000))
  if (seconds < 45) return "just now"
  var minutes = Math.round(seconds / 60)
  if (minutes < 60) return minutes + (minutes === 1 ? " minute ago" : " minutes ago")
  var hours = Math.round(minutes / 60)
  if (hours < 24) return hours + (hours === 1 ? " hour ago" : " hours ago")
  var days = Math.round(hours / 24)
  if (days < 30) return days + (days === 1 ? " day ago" : " days ago")
  return "a while ago"
}

// Status line under the panel title: the vault state, plus the sync age
// when the vault is open and the agent reported one.
function statusDetail(status, lastSync, nowMs) {
  var label = statusLabel(status)
  if (String(status) !== "unlocked") return label
  var synced = relativeSync(lastSync, nowMs)
  return synced === "" ? label : label + " · synced " + synced
}

// "12 matches" / "1 match" / "" — the pill beside the panel title while a
// search is running. Browsing shows no pill: the list is capped at the result
// limit, so a count there would describe the cap, not the vault.
function matchLabel(count) {
  var total = parseInt(count, 10)
  if (!isFinite(total) || total <= 0) return ""
  return total + (total === 1 ? " match" : " matches")
}

function sanitizeQuery(value) {
  return String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").slice(0, 512)
}

function normalizedQuery(value) {
  return sanitizeQuery(value).trim()
}

// ------------------------------------------------------------------ settings

function shouldLockForScreen(settingEnabled, screenLocked, vaultUnlocked) {
  return settingEnabled === true && screenLocked === true && vaultUnlocked === true
}

function effectiveInactivityMinutes(enabled, configured) {
  if (enabled !== true) return 0
  return boundedInt(configured, 15, 5, 240)
}

function minutesLabel(minutes) {
  var total = parseInt(minutes, 10)
  if (!isFinite(total) || total <= 0) return "Off"
  if (total % 60 === 0) return (total / 60) + (total === 60 ? " hour" : " hours")
  return total + " min"
}

function secondsLabel(seconds) {
  var total = parseInt(seconds, 10)
  if (!isFinite(total) || total <= 0) return "Off"
  if (total % 60 === 0 && total >= 120) return (total / 60) + " min"
  return total + " s"
}

if (typeof module !== "undefined") {
  module.exports = {
    defaultResponse: defaultResponse,
    parseResponse: parseResponse,
    filePath: filePath,
    bool: bool,
    boundedInt: boundedInt,
    statusLabel: statusLabel,
    statusGlyph: statusGlyph,
    tooltip: tooltip,
    serverLabel: serverLabel,
    gateCopy: gateCopy,
    setupSteps: setupSteps,
    requirementRows: requirementRows,
    itemHost: itemHost,
    isCard: isCard,
    hostEchoesName: hostEchoesName,
    itemSubtitle: itemSubtitle,
    isGroupStart: isGroupStart,
    sectionLabel: sectionLabel,
    isSectionStart: isSectionStart,
    actionAvailable: actionAvailable,
    itemActions: itemActions,
    defaultAction: defaultAction,
    primaryAction: primaryAction,
    alternateAction: alternateAction,
    actionLabel: actionLabel,
    actionGlyph: actionGlyph,
    actionTooltip: actionTooltip,
    unavailableActionTooltip: unavailableActionTooltip,
    monogram: monogram,
    copyNotice: copyNotice,
    relativeSync: relativeSync,
    statusDetail: statusDetail,
    matchLabel: matchLabel,
    sanitizeQuery: sanitizeQuery,
    normalizedQuery: normalizedQuery,
    shouldLockForScreen: shouldLockForScreen,
    effectiveInactivityMinutes: effectiveInactivityMinutes,
    minutesLabel: minutesLabel,
    secondsLabel: secondsLabel
  }
}
