// Global variables
let currentUser = null;
let charts = {};
let demoMode = false;

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatLocalDate(dateStr) {
    const [year, month, day] = dateStr.split('T')[0].split('-').map(Number);
    return new Date(year, month - 1, day).toLocaleDateString();
}

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    checkAuthStatus();
    setupEventListeners();
});

// Check authentication status
async function checkAuthStatus() {
    try {
        // First check for a Supabase session
        const { data } = await supabase.auth.getSession();
        const session = data.session;

        if (session) {
            // Sync session with Flask backend
            await fetch('/auth/session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    access_token: session.access_token
                })
            });

            currentUser = {
                id: session.user.id,
                email: session.user.email,
                name: session.user.user_metadata.name || session.user.email
            };

            showMainApp();
            await loadUserRole();
            loadDashboard();
            return;
        }

        // Fallback to server session
        const response = await fetch('/auth/user');
        if (response.ok) {
            currentUser = await response.json();
            showMainApp();
            await loadUserRole();
            loadDashboard();
        } else {
            showAuthRequired();
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        showAuthRequired();
    }
}

// Google Sign In
async function signInWithGoogle() {
    try {
        const { error } = await supabase.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo: window.location.origin
            }
        });

        if (error) throw error;
    } catch (error) {
        showAlert('Sign in failed: ' + error.message, 'danger');
    }
}

// Logout
async function logout() {
    try {
        await supabase.auth.signOut();
        await fetch('/auth/logout', { method: 'POST' });
        currentUser = null;
        showAuthRequired();
    } catch (error) {
        showAlert('Logout failed: ' + error.message, 'danger');
    }
}

// Show/hide UI sections
function showAuthRequired() {
    document.getElementById('authRequired').classList.remove('d-none');
    document.getElementById('mainApp').classList.add('d-none');
    document.getElementById('loginBtn').classList.remove('d-none');
    document.getElementById('userSection').classList.add('d-none');
    loadPublicDashboard();
}

function showMainApp() {
    document.getElementById('authRequired').classList.add('d-none');
    document.getElementById('mainApp').classList.remove('d-none');
    document.getElementById('loginBtn').classList.add('d-none');
    document.getElementById('userSection').classList.remove('d-none');

    if (currentUser) {
        document.getElementById('userName').textContent = currentUser.name || currentUser.email;
    }
}

// Load demo data for landing page
async function loadPublicDashboard() {
    loadDemoQuickStats('publicQuickStats');
    loadDemoWeekdayChart('publicWeekdayChart');
}

async function loadDemoQuickStats(elementId) {
    try {
        const response = await fetch('/api/stats/breakdown?demo=true&days=30');
        if (response.ok) {
            const data = await response.json();
            const breakdown = data.breakdown;
            document.getElementById(elementId).innerHTML = `
                <div class="row">
                    <div class="col-4">
                        <h6 class="text-success">Total Tips</h6>
                        <h4>$${breakdown.total_tips.toFixed(2)}</h4>
                    </div>
                    <div class="col-4">
                        <h6 class="text-info">Cash</h6>
                        <h5>$${breakdown.cash_tips.toFixed(2)}</h5>
                        <small class="text-muted">${breakdown.cash_percentage}%</small>
                    </div>
                    <div class="col-4">
                        <h6 class="text-warning">Card</h6>
                        <h5>$${breakdown.card_tips.toFixed(2)}</h5>
                        <small class="text-muted">${breakdown.card_percentage}%</small>
                    </div>
                </div>
            `;
        }
    } catch (error) {
        console.error('Failed to load demo quick stats:', error);
        document.getElementById(elementId).innerHTML = '<p class="text-danger">Failed to load stats</p>';
    }
}

async function loadDemoWeekdayChart(canvasId) {
    try {
        const response = await fetch('/api/stats/weekday?demo=true&days=30');
        if (response.ok) {
            const data = await response.json();
            const weekdayStats = data.weekday_stats;
            const ctx = document.getElementById(canvasId).getContext('2d');
            if (charts[canvasId]) {
                charts[canvasId].destroy();
            }
            charts[canvasId] = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: weekdayStats.map(stat => stat.weekday_name),
                    datasets: [{
                        label: 'Average Tips',
                        data: weekdayStats.map(stat => stat.avg_tips),
                        backgroundColor: '#6f42c1',
                        borderColor: '#6f42c1',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    return '$' + value.toFixed(2);
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }
    } catch (error) {
        console.error('Failed to load demo weekday chart:', error);
    }
}

// Load user role
async function loadUserRole() {
    try {
        const response = await fetch('/api/user/role');
        if (response.ok) {
            const data = await response.json();
            currentUser.role = data.role;
            const roleElement = document.getElementById('userRole');
            roleElement.textContent = data.role.charAt(0).toUpperCase() + data.role.slice(1);
            roleElement.className = `badge ${data.role === 'manager' ? 'bg-warning' : 'bg-secondary'} ms-2`;

            const userHeader = document.getElementById('userColumnHeader');
            if (userHeader) {
                if (data.role === 'manager') {
                    userHeader.classList.remove('d-none');
                } else {
                    userHeader.classList.add('d-none');
                }
            }

            const placeholder = document.querySelector('#tipsTableBody tr td');
            if (placeholder && placeholder.hasAttribute('colspan')) {
                placeholder.setAttribute('colspan', data.role === 'manager' ? 9 : 8);
            }
        }
    } catch (error) {
        console.error('Failed to load user role:', error);
    }
}

// Setup event listeners
function setupEventListeners() {
    // Tip form submission
    document.getElementById('tipForm').addEventListener('submit', handleTipSubmission);

    // Set default tip date to today
    const tipDateInput = document.getElementById('tipDate');
    if (tipDateInput) {
        tipDateInput.value = new Date().toISOString().split('T')[0];
    }
    
    // Demo mode toggle
    document.getElementById('demoModeToggle').addEventListener('change', function(e) {
        demoMode = e.target.checked;
        updateDataModeLabel();
        loadDashboard();
    });
    
    // Date filter changes
    document.querySelectorAll('input[name="dateFilter"]').forEach(radio => {
        radio.addEventListener('change', handleDateFilterChange);
    });
    
    // Custom date range inputs
    document.getElementById('startDate').addEventListener('change', handleCustomDateChange);
    document.getElementById('endDate').addEventListener('change', handleCustomDateChange);
}

// Handle tip form submission
async function handleTipSubmission(e) {
    e.preventDefault();
    
    if (demoMode) {
        showAlert('Cannot add tips in demo mode. Switch to Real Data mode.', 'warning');
        return;
    }
    
    const formData = {
        cash_tips: parseFloat(document.getElementById('cashTips').value) || 0,
        card_tips: parseFloat(document.getElementById('cardTips').value) || 0,
        hours_worked: parseFloat(document.getElementById('hoursWorked').value) || 0,
        comments: document.getElementById('comments').value.trim(),
        work_date: document.getElementById('tipDate').value || new Date().toISOString().split('T')[0]
    };
    
    const submitBtn = document.getElementById('submitTipBtn');
    const originalText = submitBtn.innerHTML;
    
    try {
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Saving...';
        submitBtn.disabled = true;
        
        const response = await fetch('/api/tips', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showAlert('Tip entry saved successfully!', 'success');
            document.getElementById('tipForm').reset();
            const tipDateInput = document.getElementById('tipDate');
            if (tipDateInput) {
                tipDateInput.value = new Date().toISOString().split('T')[0];
            }
            loadDashboard();
        } else {
            if (result.errors) {
                showAlert('Validation errors: ' + result.errors.join(', '), 'danger');
            } else {
                showAlert('Failed to save tip entry: ' + result.error, 'danger');
            }
        }
    } catch (error) {
        showAlert('Error saving tip entry: ' + error.message, 'danger');
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}

// Handle date filter changes
function handleDateFilterChange(e) {
    const customRange = document.getElementById('customDateRange');
    if (e.target.value === 'custom') {
        customRange.classList.remove('d-none');
    } else {
        customRange.classList.add('d-none');
        loadDashboard();
    }
}

// Handle custom date range changes
function handleCustomDateChange() {
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    
    if (startDate && endDate) {
        loadDashboard();
    }
}

// Update data mode label
function updateDataModeLabel() {
    const label = document.getElementById('dataModeLabel');
    label.textContent = demoMode ? 'Test Data' : 'Real Data';
}

// Get current date filter parameters
function getDateFilterParams() {
    const selectedFilter = document.querySelector('input[name="dateFilter"]:checked').value;
    const params = new URLSearchParams();
    
    if (demoMode) {
        params.append('demo', 'true');
    }
    
    if (selectedFilter === 'custom') {
        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        if (startDate && endDate) {
            params.append('start_date', startDate);
            params.append('end_date', endDate);
        }
    } else {
        params.append('days', selectedFilter);
    }
    
    return params;
}

// Load dashboard data
async function loadDashboard() {
    loadQuickStats();
    loadTipEntries();
    loadCharts();
}

// Load quick stats
async function loadQuickStats() {
    try {
        const params = getDateFilterParams();
        const response = await fetch(`/api/stats/breakdown?${params}`);
        
        if (response.ok) {
            const data = await response.json();
            const breakdown = data.breakdown;
            
            document.getElementById('quickStats').innerHTML = `
                <div class="row">
                    <div class="col-4">
                        <h6 class="text-success">Total Tips</h6>
                        <h4>$${breakdown.total_tips.toFixed(2)}</h4>
                    </div>
                    <div class="col-4">
                        <h6 class="text-info">Cash</h6>
                        <h5>$${breakdown.cash_tips.toFixed(2)}</h5>
                        <small class="text-muted">${breakdown.cash_percentage}%</small>
                    </div>
                    <div class="col-4">
                        <h6 class="text-warning">Card</h6>
                        <h5>$${breakdown.card_tips.toFixed(2)}</h5>
                        <small class="text-muted">${breakdown.card_percentage}%</small>
                    </div>
                </div>
            `;
        }
    } catch (error) {
        console.error('Failed to load quick stats:', error);
        document.getElementById('quickStats').innerHTML = '<p class="text-danger">Failed to load stats</p>';
    }
}

// Load tip entries
async function loadTipEntries() {
    try {
        const params = getDateFilterParams();
        const response = await fetch(`/api/tips?${params}`);
        const tbody = document.getElementById('tipsTableBody');
        const isManager = currentUser && currentUser.role === 'manager';
        const columnCount = isManager ? 9 : 8;

        if (response.ok) {
            const data = await response.json();
            const tips = data.tips || [];

            if (!tips.length) {
                tbody.innerHTML = `<tr><td colspan="${columnCount}" class="text-center text-muted">No entries found</td></tr>`;
                return;
            }

            tbody.innerHTML = tips.map(tip => `
                <tr>
                    <td>${formatLocalDate(tip.work_date)}</td>
                    ${isManager ? `<td>${tip.user_name ? escapeHtml(tip.user_name) : ''}</td>` : ''}
                    <td>$${tip.cash_tips.toFixed(2)}</td>
                    <td>$${tip.card_tips.toFixed(2)}</td>
                    <td>$${tip.total_tips.toFixed(2)}</td>
                    <td>${tip.hours_worked.toFixed(2)}</td>
                    <td>$${tip.tips_per_hour.toFixed(2)}</td>
                    <td>${tip.comments ? escapeHtml(tip.comments) : ''}</td>
                    <td><button class="btn btn-sm btn-outline-danger" onclick="deleteTip(${tip.id})"><i class="fas fa-trash"></i></button></td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = `<tr><td colspan="${columnCount}" class="text-center text-danger">Failed to load entries</td></tr>`;
        }
    } catch (error) {
        console.error('Failed to load tips:', error);
        const tbody = document.getElementById('tipsTableBody');
        const isManager = currentUser && currentUser.role === 'manager';
        const columnCount = isManager ? 9 : 8;
        tbody.innerHTML = `<tr><td colspan="${columnCount}" class="text-center text-danger">Failed to load entries</td></tr>`;
    }
}

// Delete a tip entry
async function deleteTip(id) {
    if (demoMode) {
        showAlert('Cannot delete tips in demo mode. Switch to Real Data mode.', 'warning');
        return;
    }

    if (!confirm('Delete this tip entry?')) {
        return;
    }

    try {
        const response = await fetch(`/api/tips/${id}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showAlert('Tip entry deleted', 'success');
            loadDashboard();
        } else {
            const result = await response.json();
            showAlert('Failed to delete tip entry: ' + (result.error || 'Unknown error'), 'danger');
        }
    } catch (error) {
        showAlert('Error deleting tip entry: ' + error.message, 'danger');
    }
}

// Load all charts
async function loadCharts() {
    await Promise.all([
        loadDailyChart(),
        loadBreakdownChart(),
        loadWeekdayChart(),
        loadHourlyChart()
    ]);
}

// Load daily chart
async function loadDailyChart() {
    try {
        const params = getDateFilterParams();
        const response = await fetch(`/api/stats/daily?${params}`);
        
        if (response.ok) {
            const data = await response.json();
            const dailyStats = data.daily_stats;
            
            const ctx = document.getElementById('dailyChart').getContext('2d');
            
            // Destroy existing chart
            if (charts.daily) {
                charts.daily.destroy();
            }
            
            charts.daily = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: dailyStats.map(stat => formatLocalDate(stat.date)),
                    datasets: [{
                        label: 'Total Tips',
                        data: dailyStats.map(stat => stat.total_tips),
                        borderColor: '#20c997',
                        backgroundColor: '#20c99720',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    return '$' + value.toFixed(2);
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        }
                    }
                }
            });
        }
    } catch (error) {
        console.error('Failed to load daily chart:', error);
    }
}

// Load breakdown chart
async function loadBreakdownChart() {
    try {
        const params = getDateFilterParams();
        const response = await fetch(`/api/stats/breakdown?${params}`);
        
        if (response.ok) {
            const data = await response.json();
            const breakdown = data.breakdown;
            
            const ctx = document.getElementById('breakdownChart').getContext('2d');
            
            // Destroy existing chart
            if (charts.breakdown) {
                charts.breakdown.destroy();
            }
            
            charts.breakdown = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['Cash Tips', 'Card Tips'],
                    datasets: [{
                        data: [breakdown.cash_tips, breakdown.card_tips],
                        backgroundColor: ['#ffc107', '#0d6efd'],
                        borderColor: ['#ffc107', '#0d6efd'],
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom'
                        }
                    }
                }
            });
        }
    } catch (error) {
        console.error('Failed to load breakdown chart:', error);
    }
}

// Load weekday chart
async function loadWeekdayChart() {
    try {
        const params = getDateFilterParams();
        const response = await fetch(`/api/stats/weekday?${params}`);
        
        if (response.ok) {
            const data = await response.json();
            const weekdayStats = data.weekday_stats;
            
            const ctx = document.getElementById('weekdayChart').getContext('2d');
            
            // Destroy existing chart
            if (charts.weekday) {
                charts.weekday.destroy();
            }
            
            charts.weekday = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: weekdayStats.map(stat => stat.weekday_name),
                    datasets: [{
                        label: 'Average Tips',
                        data: weekdayStats.map(stat => stat.avg_tips),
                        backgroundColor: '#6f42c1',
                        borderColor: '#6f42c1',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    return '$' + value.toFixed(2);
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        }
                    }
                }
            });
        }
    } catch (error) {
        console.error('Failed to load weekday chart:', error);
    }
}

// Load hourly chart
async function loadHourlyChart() {
    try {
        const params = getDateFilterParams();
        const response = await fetch(`/api/stats/daily?${params}`);
        
        if (response.ok) {
            const data = await response.json();
            const dailyStats = data.daily_stats;
            
            const ctx = document.getElementById('hourlyChart').getContext('2d');
            
            // Destroy existing chart
            if (charts.hourly) {
                charts.hourly.destroy();
            }
            
            charts.hourly = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dailyStats.map(stat => formatLocalDate(stat.date)),
                    datasets: [{
                        label: 'Tips per Hour',
                        data: dailyStats.map(stat => stat.avg_tips_per_hour),
                        backgroundColor: '#dc3545',
                        borderColor: '#dc3545',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    return '$' + value.toFixed(2);
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        }
                    }
                }
            });
        }
    } catch (error) {
        console.error('Failed to load hourly chart:', error);
    }
}

// Utility function to show alerts
function showAlert(message, type = 'info') {
    const alertArea = document.getElementById('alertArea');
    const alertId = 'alert-' + Date.now();
    
    const alertHtml = `
        <div id="${alertId}" class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    alertArea.insertAdjacentHTML('beforeend', alertHtml);
    
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        const alert = document.getElementById(alertId);
        if (alert) {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }
    }, 5000);
}
