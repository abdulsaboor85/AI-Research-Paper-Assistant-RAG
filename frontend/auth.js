/* ==========================================================
   auth.js  —  PaperMind login / signup logic
   ========================================================== */

const API = "http://127.0.0.1:5000";

/* ── Dark mode ───────────────────────────────────────────── */

function toggleAuthDark() {
  const isDark = document.body.classList.toggle("dark");
  const btn    = document.getElementById("authDarkBtn");
  if (btn) btn.textContent = isDark ? "☀️" : "🌙";
  localStorage.setItem("papermind_darkMode", String(isDark));
}

// Apply saved dark mode on load
(function applyDark() {
  if (localStorage.getItem("papermind_darkMode") === "true") {
    document.body.classList.add("dark");
    const btn = document.getElementById("authDarkBtn");
    if (btn) btn.textContent = "☀️";
  }
})();

/* ── Mode switching ──────────────────────────────────────── */

function switchMode(mode) {
  const isLogin = mode === "login";

  document.getElementById("loginForm").style.display  = isLogin ? "" : "none";
  document.getElementById("signupForm").style.display = isLogin ? "none" : "";

  document.getElementById("loginTab").classList.toggle("active",  isLogin);
  document.getElementById("signupTab").classList.toggle("active", !isLogin);

  clearErrors();
}

function clearErrors() {
  ["loginError", "signupError"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.display = "none";
      el.textContent   = "";
    }
  });
  document.querySelectorAll(".field-input").forEach(i => {
    i.classList.remove("error");
  });
}

/* ── Show error ──────────────────────────────────────────── */

function showError(formType, message) {
  const el = document.getElementById(formType + "Error");
  if (!el) return;
  el.textContent    = message;
  el.style.display  = "block";
}

/* ── Loading state ───────────────────────────────────────── */

function setLoading(formType, loading) {
  const btn     = document.getElementById(formType + "Btn");
  const text    = document.getElementById(formType + "BtnText");
  const spinner = document.getElementById(formType + "Spinner");

  if (!btn) return;
  btn.disabled           = loading;
  text.style.display     = loading ? "none" : "";
  spinner.style.display  = loading ? "inline-block" : "none";
}

/* ── Password visibility toggle ─────────────────────────── */

function togglePass(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;

  const show = input.type === "password";
  input.type = show ? "text" : "password";

  // Eye open (visible) vs eye with slash (hidden)
  btn.innerHTML = show
    ? `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6">
         <path d="M1 10s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z"/>
         <circle cx="10" cy="10" r="2.5"/>
         <line x1="3" y1="3" x2="17" y2="17"/>
       </svg>`
    : `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6">
         <path d="M1 10s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z"/>
         <circle cx="10" cy="10" r="2.5"/>
       </svg>`;
}

/* ── Enter key handler ───────────────────────────────────── */

function handleKey(event, formType) {
  if (event.key === "Enter") {
    event.preventDefault();
    if (formType === "login")  doLogin();
    if (formType === "signup") doSignup();
  }
}

/* ── LOGIN ───────────────────────────────────────────────── */

async function doLogin() {
  clearErrors();

  const usernameEl = document.getElementById("loginUser");
  const passwordEl = document.getElementById("loginPass");

  const username = usernameEl.value.trim();
  const password = passwordEl.value;

  if (!username) {
    usernameEl.classList.add("error");
    showError("login", "Please enter your username or email.");
    return;
  }

  if (!password) {
    passwordEl.classList.add("error");
    showError("login", "Please enter your password.");
    return;
  }

  setLoading("login", true);

  try {
    const response = await fetch(`${API}/api/login`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ username, password }),
    });

    const data = await response.json();

    if (!response.ok) {
      passwordEl.classList.add("error");
      showError("login", data.error || "Login failed. Please check your credentials.");
      return;
    }

    window.location.href = "/";

  } catch {
    showError("login", "Cannot reach the server. Make sure Flask is running.");
  } finally {
    setLoading("login", false);
  }
}

/* ── SIGNUP ──────────────────────────────────────────────── */

async function doSignup() {
  clearErrors();

  const usernameEl = document.getElementById("signupUser");
  const emailEl    = document.getElementById("signupEmail");
  const passwordEl = document.getElementById("signupPass");

  const username = usernameEl.value.trim();
  const email    = emailEl.value.trim();
  const password = passwordEl.value;

  let hasError = false;

  if (!username || username.length < 3) {
    usernameEl.classList.add("error");
    hasError = true;
  }

  if (!email || !email.includes("@")) {
    emailEl.classList.add("error");
    hasError = true;
  }

  if (!password || password.length < 6) {
    passwordEl.classList.add("error");
    hasError = true;
  }

  if (hasError) {
    showError("signup", "Please fill in all fields correctly before continuing.");
    return;
  }

  setLoading("signup", true);

  try {
    const response = await fetch(`${API}/api/signup`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ username, email, password }),
    });

    const data = await response.json();

    if (!response.ok) {
      showError("signup", data.error || "Signup failed. Please try again.");

      if (data.error && data.error.toLowerCase().includes("username")) {
        usernameEl.classList.add("error");
      } else if (data.error && data.error.toLowerCase().includes("email")) {
        emailEl.classList.add("error");
      }

      return;
    }

    window.location.href = "/";

  } catch {
    showError("signup", "Cannot reach the server. Make sure Flask is running.");
  } finally {
    setLoading("signup", false);
  }
}

/* ── Expose to HTML onclick ──────────────────────────────── */

window.toggleAuthDark = toggleAuthDark;
window.switchMode     = switchMode;
window.doLogin        = doLogin;
window.doSignup       = doSignup;
window.togglePass     = togglePass;
window.handleKey      = handleKey;