'use strict';
let connectionState = null;
let issuing = false;
const field = id => document.getElementById(id);

function status(message) { field('accessStatus').textContent = message; }
function clearToken() {
    field('issuedToken').value = '';
    field('tokenReveal').hidden = true;
}

async function requestAccess(url, options = {}) {
    let response;
    try { response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options}); }
    catch { throw new Error('The action could not be confirmed. Refresh connections before trying again.'); }
    if (!response.ok) {
        if (response.status === 401) {
            clearToken();
            field('signInLink').hidden = false;
            throw new Error('Sign in on the dashboard again, then return here.');
        }
        if (response.status === 409) throw new Error('That request was already used. Refresh connections and revoke any token you could not save.');
        throw new Error('The action could not be confirmed. Refresh connections before trying again.');
    }
    try { return await response.json(); }
    catch { throw new Error('The response could not be verified. Refresh connections before trying again.'); }
}

function renderConnections(records, append = false) {
    const list = field('connectionList');
    if (!append) list.replaceChildren();
    if (!records.length) {
        const empty = document.createElement('p');
        empty.textContent = 'No connections yet.';
        list.append(empty);
    }
    for (const record of records) {
        const row = document.createElement('div');
        row.className = 'connection';
        const description = document.createElement('div');
        const name = document.createElement('strong');
        name.textContent = record.client_id;
        const detail = document.createElement('p');
        const expired = record.expires_at * 1000 <= Date.now();
        detail.textContent = `${record.revoked ? 'Revoked' : expired ? 'Expired' : 'Active'} · ${record.scopes.join(', ')} · expires ${new Date(record.expires_at * 1000).toLocaleString()}`;
        description.append(name, detail);
        row.append(description);
        if (!record.revoked && !expired) {
            const revoke = document.createElement('button');
            revoke.type = 'button';
            revoke.className = 'secondary';
            revoke.textContent = 'Revoke';
            revoke.addEventListener('click', async () => {
                if (!connectionState || !window.confirm(`Revoke ${record.client_id}? Future API requests with this token will be rejected.`)) return;
                revoke.disabled = true;
                try {
                    await requestAccess(`/api/integration-access/grants/${encodeURIComponent(record.id)}/revoke`, {
                        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': connectionState.csrf_token},
                        body: JSON.stringify({revoke: true})
                    });
                    clearToken();
                    await loadConnections();
                    status('Connection revoked. Previously read data may remain with the client.');
                } catch (error) { status(error.message); revoke.disabled = false; }
            });
            row.append(revoke);
        }
        list.append(row);
    }
}

async function loadConnections({preserveReveal = false, older = false} = {}) {
    if (!preserveReveal) clearToken();
    const offset = older && connectionState ? connectionState.next_offset : null;
    connectionState = null;
    field('connectionSetup').hidden = true;
    if (!older) field('connectionList').replaceChildren();
    field('olderConnections').hidden = true;
    field('signInLink').hidden = true;
    try {
        const data = await requestAccess('/api/integration-access' + (offset != null ? `?offset=${offset}` : ''));
        connectionState = data;
        field('accessAccount').textContent = data.account;
        field('connectionSetup').hidden = false;
        renderConnections(data.connections, older);
        field('olderConnections').hidden = data.next_offset == null;
        status('Your sign-in is verified. New connections are read-only.');
    } catch (error) { clearToken(); status(error.message); }
}

async function issueConnection(event) {
    event.preventDefault();
    if (issuing || !connectionState || !field('readConsent').checked) return;
    if (!field('connectionForm').reportValidity()) return;
    issuing = true;
    field('createConnection').disabled = true;
    clearToken();
    try {
        const data = await requestAccess('/api/integration-access/grants', {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': connectionState.csrf_token},
            body: JSON.stringify({client_id: field('clientId').value, expires_in_hours: Number(field('expiryHours').value),
                consent: connectionState.consent, issuance_id: connectionState.issuance_id})
        });
        field('issuedToken').value = data.token;
        field('issuedServer').textContent = `${window.location.origin}/api/integrations/v1`;
        field('issuedClient').textContent = data.client_id;
        field('issuedExpiry').textContent = new Date(data.expires_at * 1000).toLocaleString();
        field('tokenReveal').hidden = false;
        field('readConsent').checked = false;
        await loadConnections({preserveReveal: true});
    } catch (error) {
        connectionState = null;
        field('connectionSetup').hidden = true;
        status(error.message);
    } finally {
        issuing = false;
        field('createConnection').disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    field('connectionForm').addEventListener('submit', issueConnection);
    field('refreshConnections').addEventListener('click', () => loadConnections());
    field('olderConnections').addEventListener('click', () => loadConnections({older: true}));
    field('hideToken').addEventListener('click', clearToken);
    field('copyToken').addEventListener('click', async () => {
        const token = field('issuedToken').value;
        if (!token) return;
        try { await navigator.clipboard.writeText(token); status('Token copied. Save it securely, then clear it from this page.'); }
        catch { status('Copy was unavailable. Select the token and copy it manually.'); }
    });
    loadConnections();
});
window.addEventListener('pagehide', clearToken);
