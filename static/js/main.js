const sessionId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
const form = document.getElementById("chatForm");
const input = document.getElementById("messageInput");
const messages = document.getElementById("messages");
const meetingList = document.getElementById("meetingList");

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
}

function addMessage(text, sender) {
    const row = document.createElement("div");
    row.className = `message-row ${sender}`;
    if (sender === "bot") {
        row.innerHTML = `<div class="avatar">助</div><div class="bubble">${escapeHtml(text)}</div>`;
    } else {
        row.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
    }
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
}

function updateDraft(draft) {
    document.getElementById("draftName").textContent = draft?.name || "尚未填寫";
    document.getElementById("draftTime").textContent = draft?.time || "尚未填寫";
    document.getElementById("draftLocation").textContent = draft?.location || "尚未填寫";
}

async function loadMeetings() {
    const response = await fetch("/api/meetings");
    const meetings = await response.json();
    document.getElementById("meetingCount").textContent = meetings.length;
    if (!meetings.length) {
        meetingList.innerHTML = `<div class="empty-history">尚未保存會議</div>`;
        return;
    }
    meetingList.innerHTML = meetings.map(meeting => `
        <article class="meeting-card">
            <h3>${escapeHtml(meeting.name)}</h3>
            <p>🕘 ${escapeHtml(meeting.time)}</p>
            <p>📍 ${escapeHtml(meeting.location)}</p>
        </article>
    `).join("");
}

form.addEventListener("submit", async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;

    addMessage(message, "user");
    input.value = "";

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({session_id: sessionId, message})
        });
        const data = await response.json();
        addMessage(data.reply, "bot");
        updateDraft(data.draft);
        if (data.meeting) loadMeetings();
    } catch (error) {
        addMessage("目前無法連線，請稍後再試一次。", "bot");
    }
});

document.getElementById("resetBtn").addEventListener("click", async () => {
    const response = await fetch("/api/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, message: "重新開始"})
    });
    const data = await response.json();
    updateDraft(data.draft);
    addMessage("已清除目前的會議資料。", "bot");
});

updateDraft({name: null, time: null, location: null});
loadMeetings();
