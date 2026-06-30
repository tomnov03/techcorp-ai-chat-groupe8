// === TechCorp AI Chat — Frontend logic ===
// Parle exclusivement au backend proxy (/api/...), qui lui-même
// redirige vers Ollama / Triton / serveur maison selon la config INFRA.

const API_BASE = ""; // même origine que le frontend (servi par le backend)

const messagesEl = document.getElementById("messages");
const emptyState = document.getElementById("empty-state");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const newChatBtn = document.getElementById("new-chat");
const statusDot = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const statusMeta = document.getElementById("status-meta");
const tickerTrack = document.getElementById("ticker-track");

let history = []; // [{role, content}]
let isStreaming = false;

// ---------- Health check ----------

async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) throw new Error("unhealthy");
    const data = await res.json();
    statusDot.classList.add("ok");
    statusLabel.textContent = `Backend: ${data.backend}`;
    statusMeta.textContent = `${data.model} · ${data.inference_url}`;
  } catch (e) {
    statusDot.classList.add("err");
    statusLabel.textContent = "Serveur injoignable";
    statusMeta.textContent = "Vérifiez que le backend tourne (uvicorn).";
  }
}
checkHealth();
setInterval(checkHealth, 15000);

// ---------- Ticker décoratif ----------
const tickerItems = [
  "PHI-3.5-FINANCIAL · STATUS: ONLINE",
  "LATENCY: streaming",
  "MODE: production",
  "TECHCORP INDUSTRIES",
  "INTERFACE: dev web team",
];
tickerTrack.innerHTML = [...tickerItems, ...tickerItems]
  .map((t) => `<span>${t}</span>`)
  .join("");

// ---------- Auto-resize textarea ----------
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll(".suggestion").forEach((btn) => {
  btn.addEventListener("click", () => {
    input.value = btn.dataset.prompt;
    form.requestSubmit();
  });
});

newChatBtn.addEventListener("click", () => {
  history = [];
  messagesEl.innerHTML = "";
  messagesEl.appendChild(emptyState);
  emptyState.style.display = "block";
});

// ---------- Rendering ----------

function addMessage(role, content) {
  emptyState.style.display = "none";
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "VOUS" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

// ---------- Submit handler ----------

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || isStreaming) return;

  input.value = "";
  input.style.height = "auto";

  history.push({ role: "user", content: text });
  addMessage("user", text);

  const assistantBubble = addMessage("assistant", "");
  assistantBubble.classList.add("streaming");

  isStreaming = true;
  sendBtn.disabled = true;

  let fullText = "";

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });

    if (!res.ok || !res.body) {
      const errText = await res.text();
      throw new Error(errText || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // dernière ligne potentiellement incomplète

      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (payload === "[DONE]") continue;
        try {
          const parsed = JSON.parse(payload);
          if (parsed.token) {
            fullText += parsed.token;
            assistantBubble.textContent = fullText;
            messagesEl.scrollTop = messagesEl.scrollHeight;
          }
        } catch (_) {
          /* ignore lignes mal formées */
        }
      }
    }

    history.push({ role: "assistant", content: fullText });
  } catch (err) {
    assistantBubble.classList.add("error-bubble");
    assistantBubble.textContent =
      "Erreur de connexion au serveur d'inférence : " + err.message;
  } finally {
    assistantBubble.classList.remove("streaming");
    isStreaming = false;
    sendBtn.disabled = false;
  }
});
