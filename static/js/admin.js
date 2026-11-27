const monthPicker = document.getElementById("monthPicker");
const calendarGrid = document.getElementById("calendarGrid");
const detailList = document.getElementById("reservationDetails");
const errorPanel = document.getElementById("loadError");
let monthData = null;
let selectedDate = null;

const today = new Date();
monthPicker.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;

function escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = String(value ?? "");
    return element.innerHTML;
}

function formatTable(tableId) {
    const [seats, number] = tableId.split("-");
    return `${escapeHtml(seats)}人桌${escapeHtml(number)}`;
}

function showError(message) {
    errorPanel.textContent = message;
    errorPanel.classList.remove("hidden");
}

function monthDate(value) {
    const [year, month] = value.split("-").map(Number);
    return new Date(year, month - 1, 1);
}

function renderCalendar() {
    const first = monthDate(monthData.month);
    const year = first.getFullYear();
    const monthIndex = first.getMonth();
    const offset = (first.getDay() + 6) % 7;
    const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
    const previousDays = new Date(year, monthIndex, 0).getDate();
    const totalCells = Math.ceil((offset + daysInMonth) / 7) * 7;

    document.getElementById("calendarTitle").textContent = `${year} 年 ${monthIndex + 1} 月`;
    calendarGrid.innerHTML = "";
    for (let index = 0; index < totalCells; index += 1) {
        const dayNumber = index - offset + 1;
        const isCurrentMonth = dayNumber >= 1 && dayNumber <= daysInMonth;
        const visibleDay = dayNumber < 1 ? previousDays + dayNumber : dayNumber > daysInMonth ? dayNumber - daysInMonth : dayNumber;
        const dateString = isCurrentMonth
            ? `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(dayNumber).padStart(2, "0")}`
            : "";
        const summary = dateString ? monthData.daily[dateString] : null;
        const button = document.createElement("button");
        button.type = "button";
        button.className = `calendar-day${isCurrentMonth ? "" : " is-outside"}${dateString === selectedDate ? " is-selected" : ""}`;
        button.setAttribute("aria-label", isCurrentMonth
            ? `${dateString}，${summary?.guests || 0} 位客人，${summary?.count || 0} 筆訂位`
            : `${visibleDay} 日`);
        button.innerHTML = `<span class="day-number">${visibleDay}</span>${
            summary?.count ? `<span class="day-metrics"><b>${summary.guests} 位</b>${summary.count} 筆訂位</span>` : ""
        }`;
        if (isCurrentMonth) {
            button.addEventListener("click", () => selectDay(dateString));
        } else {
            button.disabled = true;
        }
        calendarGrid.appendChild(button);
    }

    const reservations = monthData.reservations.filter(item => item.status === "confirmed");
    document.getElementById("monthlyReservations").textContent = reservations.length;
    document.getElementById("monthlyGuests").textContent = reservations.reduce((total, item) => total + item.party_size, 0);
}

function selectDay(dateString) {
    selectedDate = dateString;
    renderCalendar();
    const summary = monthData.daily[dateString];
    document.getElementById("selectedDateTitle").textContent = dateString;
    document.getElementById("selectedGuestTotal").textContent = `${summary?.guests || 0} 位`;
    if (!summary?.reservations.length) {
        detailList.innerHTML = `<p class="empty-state">當日沒有訂位紀錄。</p>`;
        return;
    }
    detailList.innerHTML = summary.reservations.map(item => `
        <article class="reservation-item">
            <div class="reservation-item-head">
                <strong>${escapeHtml(item.reservation_time)}　${escapeHtml(item.guest_name)}</strong>
                <span>${item.party_size} 位</span>
            </div>
            <p>訂位 #${item.id}　桌位：${item.table_ids.map(formatTable).join("、")}</p>
            ${item.status === "confirmed"
                ? `<button class="cancel-booking" type="button" data-id="${item.id}">取消此預約</button>`
                : `<p class="reservation-status">已取消</p>`}
        </article>
    `).join("");
    detailList.querySelectorAll(".cancel-booking").forEach(button => {
        button.addEventListener("click", () => cancelReservation(button.dataset.id));
    });
}

async function loadMonth() {
    errorPanel.classList.add("hidden");
    try {
        const response = await fetch(`/api/admin/month?month=${encodeURIComponent(monthPicker.value)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "載入月曆失敗");
        monthData = data;
        if (!selectedDate || !selectedDate.startsWith(data.month)) {
            selectedDate = `${data.month}-01`;
        }
        renderCalendar();
        selectDay(selectedDate);
    } catch (error) {
        showError(error.message);
    }
}

async function cancelReservation(id) {
    if (!window.confirm(`確定取消預約 #${id} 嗎？`)) return;
    try {
        const response = await fetch(`/api/admin/reservations/${id}/cancel`, {
            method: "POST",
            headers: {"X-CSRF-Token": window.adminCsrfToken}
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "取消預約失敗");
        await loadMonth();
    } catch (error) {
        showError(error.message);
    }
}

monthPicker.addEventListener("change", loadMonth);
document.getElementById("previousMonth").addEventListener("click", () => {
    const date = monthDate(monthPicker.value);
    date.setMonth(date.getMonth() - 1);
    monthPicker.value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    loadMonth();
});
document.getElementById("nextMonth").addEventListener("click", () => {
    const date = monthDate(monthPicker.value);
    date.setMonth(date.getMonth() + 1);
    monthPicker.value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    loadMonth();
});

loadMonth();
