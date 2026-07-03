document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const patientSelect = document.getElementById('patientSelect');
    const queryInput = document.getElementById('queryInput');
    const sendBtn = document.getElementById('sendBtn');
    const chatHistory = document.getElementById('chatHistory');
    const agentStatus = document.getElementById('agentStatus');
    const resetDbBtn = document.getElementById('resetDbBtn');
    
    // Tab Elements
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    // Panel Elements
    const jsonOutput = document.getElementById('jsonOutput');
    const taskTrace = document.getElementById('taskTrace');
    const messageTrace = document.getElementById('messageTrace');
    const systemLogs = document.getElementById('systemLogs');
    
    // Modal Elements
    const modal = document.getElementById('patientModal');
    const closeModal = document.querySelector('.close');
    const viewPatientBtn = document.getElementById('viewPatientBtn');
    const newPatientBtn = document.getElementById('newPatientBtn');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');

    // Global state
    let isProcessing = false;

    // Load initial patients
    loadPatients();

    // ──────────────────────────────────────────────────────────────────
    // Event Listeners
    // ──────────────────────────────────────────────────────────────────

    sendBtn.addEventListener('click', handleSend);
    
    queryInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    });

    resetDbBtn.addEventListener('click', async () => {
        if(confirm("Are you sure you want to reset the database to seed data?")) {
            try {
                await fetch('/api/reset', { method: 'POST' });
                alert("Database reset successfully!");
                loadPatients();
            } catch (err) {
                console.error(err);
                alert("Failed to reset DB.");
            }
        }
    });

    // Tab Switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab + 'Tab').classList.add('active');
        });
    });

    // Modal Actions
    viewPatientBtn.addEventListener('click', (e) => {
        e.preventDefault();
        showPatientDetails(patientSelect.value);
    });

    newPatientBtn.addEventListener('click', (e) => {
        e.preventDefault();
        showNewPatientForm();
    });

    closeModal.addEventListener('click', () => {
        modal.classList.remove('show');
    });

    window.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('show');
        }
    });

    // Helper for example clicks
    window.setQuery = (text) => {
        queryInput.value = text;
        queryInput.focus();
    };

    // ──────────────────────────────────────────────────────────────────
    // API Calls & Logic
    // ──────────────────────────────────────────────────────────────────

    async function loadPatients() {
        try {
            const res = await fetch('/api/patients');
            const data = await res.json();
            
            // Keep current selection if exists
            const currentVal = patientSelect.value;
            
            patientSelect.innerHTML = '';
            data.patients.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.patient_id;
                opt.textContent = `${p.patient_id} - ${p.name}`;
                patientSelect.appendChild(opt);
            });
            
            if (currentVal && Array.from(patientSelect.options).some(o => o.value === currentVal)) {
                patientSelect.value = currentVal;
            }
        } catch (err) {
            console.error("Failed to load patients", err);
        }
    }

    async function handleSend() {
        const query = queryInput.value.trim();
        const patientId = patientSelect.value;
        
        if (!query || isProcessing) return;
        
        // Update UI
        isProcessing = true;
        sendBtn.disabled = true;
        queryInput.value = '';
        agentStatus.textContent = 'Processing...';
        agentStatus.className = 'status-badge running';
        
        // Add user message to chat
        addChatMessage(query, 'user');
        
        try {
            const res = await fetch('/api/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ patient_id: patientId, query: query })
            });
            
            const data = await res.json();
            
            if (!res.ok) throw new Error(data.detail || "Server error");
            
            // Process response
            addChatMessage(data, 'system');
            updateSidePanels(data);
            
        } catch (err) {
            addChatMessage({ summary: `Error: ${err.message}` }, 'system', true);
        } finally {
            isProcessing = false;
            sendBtn.disabled = false;
            agentStatus.textContent = 'Idle';
            agentStatus.className = 'status-badge idle';
            queryInput.focus();
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // UI Updaters
    // ──────────────────────────────────────────────────────────────────

    function addChatMessage(content, sender, isError = false) {
        // Remove welcome message if present
        const welcome = chatHistory.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;
        
        let innerHtml = '';
        if (sender === 'user') {
            innerHtml = `
                <div class="msg-header">You</div>
                <div class="msg-bubble">${content}</div>
            `;
        } else {
            // System response formatting
            let cardHtml = `<div class="msg-bubble">`;
            if (isError) {
                cardHtml += `<span style="color:var(--danger)"><i class="fa-solid fa-triangle-exclamation"></i> ${content.summary}</span>`;
            } else {
                cardHtml += `<strong><i class="fa-solid fa-robot"></i> Task Completed (${content.elapsed_ms}ms)</strong>`;
                cardHtml += `<div class="result-card">`;
                
                const rows = [
                    { label: 'Summary', val: content.summary },
                    { label: 'Appointment', val: content.appointment_status },
                    { label: 'Lab Test', val: content.lab_test_status },
                    { label: 'Notification', val: content.notification_status }
                ];
                
                rows.forEach(r => {
                    if (r.val && r.val !== 'N/A') {
                        cardHtml += `
                            <div class="result-row">
                                <div class="result-label">${r.label}:</div>
                                <div class="result-value">${r.val}</div>
                            </div>
                        `;
                    }
                });
                cardHtml += `</div>`;
            }
            cardHtml += `</div>`;
            
            innerHtml = `
                <div class="msg-header">Hospital AI</div>
                ${cardHtml}
            `;
        }
        
        msgDiv.innerHTML = innerHtml;
        chatHistory.appendChild(msgDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function updateSidePanels(data) {
        // 1. Output JSON
        const outData = {
            summary: data.summary,
            appointment_status: data.appointment_status,
            lab_test_status: data.lab_test_status,
            notification_status: data.notification_status,
            elapsed_ms: data.elapsed_ms,
            retries: data.retry_count
        };
        jsonOutput.textContent = JSON.stringify(outData, null, 2);

        // 2. Task Trace
        taskTrace.innerHTML = '';
        if (data.task_trace) {
            data.task_trace.forEach(task => {
                let statusClass = '';
                if(task.status === 'done') statusClass = 'status-done';
                if(task.status === 'failed') statusClass = 'status-failed';
                if(task.status === 'skipped') statusClass = 'status-skipped';
                if(task.status === 'running') statusClass = 'status-running';
                
                const dur = task.duration_ms ? ` (${task.duration_ms}ms)` : '';
                const err = task.error ? `<br><small style="color:var(--danger)">Error: ${task.error}</small>` : '';
                
                const el = document.createElement('div');
                el.className = 'trace-item';
                el.innerHTML = `
                    <span class="${statusClass}">[${task.status.toUpperCase()}]</span> 
                    <strong>${task.kind}</strong> 
                    <i class="fa-solid fa-arrow-right" style="font-size:0.8em; color:#94a3b8"></i> 
                    <span class="agent-name">${task.agent}</span>${dur}
                    ${err}
                `;
                taskTrace.appendChild(el);
            });
        }

        // 3. Messages
        messageTrace.innerHTML = '';
        if (data.message_trace) {
            data.message_trace.forEach(msg => {
                const el = document.createElement('div');
                el.className = 'msg-item';
                el.innerHTML = `
                    <span style="color:var(--text-muted)">[${msg.sender}] &rarr; [${msg.receiver}]</span><br>
                    <span>${msg.content}</span>
                `;
                messageTrace.appendChild(el);
            });
        }

        // 4. Logs
        systemLogs.innerHTML = '';
        if (data.logs) {
            data.logs.forEach(log => {
                let lvlClass = 'log-info';
                if(log.level === 'WARNING') lvlClass = 'log-warning';
                if(log.level === 'ERROR' || log.level === 'CRITICAL') lvlClass = 'log-error';
                
                const el = document.createElement('div');
                el.className = `log-item ${lvlClass}`;
                el.innerHTML = `
                    <span class="log-time">[${log.timestamp}]</span>
                    <strong>[${log.icon}] ${log.agent}</strong> | ${log.message}
                `;
                systemLogs.appendChild(el);
            });
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // Modal Handlers
    // ──────────────────────────────────────────────────────────────────

    async function showPatientDetails(patientId) {
        try {
            const res = await fetch(`/api/patients/${patientId}`);
            if (!res.ok) throw new Error("Not found");
            const data = await res.json();
            
            modalTitle.textContent = `Patient: ${data.patient.name}`;
            
            let html = `
                <div style="margin-bottom:15px; background:#f8fafc; padding:15px; border-radius:6px; border:1px solid #e2e8f0;">
                    <p><strong>ID:</strong> ${data.patient.patient_id}</p>
                    <p><strong>Age:</strong> ${data.patient.age || 'N/A'}</p>
                    <p><strong>Contact:</strong> ${data.patient.phone || 'N/A'} | ${data.patient.email || 'N/A'}</p>
                </div>
                
                <h3>Recent Appointments</h3>
                <ul style="margin-bottom:15px; padding-left:20px; font-size:0.9rem;">
            `;
            
            if (data.appointment_details.length === 0) {
                html += `<li>No appointments found.</li>`;
            } else {
                data.appointment_details.forEach(a => {
                    html += `<li><strong>${a.slot_time}</strong> - ${a.doctor_name} (${a.specialization}) - <span style="color:var(--success)">${a.status}</span></li>`;
                });
            }
            
            html += `
                </ul>
                <h3>Lab Reports</h3>
                <ul style="padding-left:20px; font-size:0.9rem;">
            `;
            
            if (data.lab_reports.length === 0) {
                html += `<li>No lab reports found.</li>`;
            } else {
                data.lab_reports.forEach(l => {
                    let color = l.status === 'Completed' ? 'var(--success)' : 'var(--warning)';
                    html += `<li><strong>${l.test_name}</strong> - <span style="color:${color}">${l.status}</span></li>`;
                });
            }
            
            html += `</ul>`;
            
            modalBody.innerHTML = html;
            modal.classList.add('show');
            
        } catch (err) {
            alert("Could not load patient details.");
        }
    }

    function showNewPatientForm() {
        modalTitle.textContent = "Add New Patient";
        modalBody.innerHTML = `
            <form id="newPatientForm" style="display:flex; flex-direction:column; gap:10px;">
                <input type="text" id="npId" placeholder="Patient ID (e.g., P003)" required style="padding:8px;">
                <input type="text" id="npName" placeholder="Full Name" required style="padding:8px;">
                <input type="number" id="npAge" placeholder="Age" required style="padding:8px;">
                <input type="text" id="npPhone" placeholder="Phone" style="padding:8px;">
                <input type="email" id="npEmail" placeholder="Email" style="padding:8px;">
                <button type="submit" class="btn-primary" style="margin-top:10px;">Add Patient</button>
            </form>
        `;
        
        modal.classList.add('show');
        
        document.getElementById('newPatientForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const payload = {
                patient_id: document.getElementById('npId').value,
                name: document.getElementById('npName').value,
                age: parseInt(document.getElementById('npAge').value),
                phone: document.getElementById('npPhone').value,
                email: document.getElementById('npEmail').value,
            };
            
            try {
                const res = await fetch('/api/patients', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) throw new Error(await res.text());
                
                alert("Patient added successfully!");
                modal.classList.remove('show');
                await loadPatients();
                patientSelect.value = payload.patient_id;
            } catch (err) {
                alert(`Failed: ${err.message}`);
            }
        });
    }
});
