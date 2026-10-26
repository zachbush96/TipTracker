const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const source = readFileSync(resolve(__dirname, '../static/js/integration-access.js'), 'utf8');

function setup({postStatus = 201, fail = false, records = []} = {}) {
    const elements = new Map();
    const requests = [];
    const handlers = {};
    const token = 'synthetic-one-time-token';
    const element = () => ({value: '', textContent: '', checked: false, hidden: false, disabled: false,
        children: [], listeners: {}, append(...items) {this.children.push(...items);},
        replaceChildren(...items) {this.children = items;}, reportValidity() {return true;},
        addEventListener(name, fn) {this.listeners[name] = fn;}});
    const field = id => {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);};
    const state = {account: 'synthetic@example.invalid', csrf_token: 'synthetic-csrf',
        issuance_id: 'synthetic-issuance', consents: {read: 'read-only-own-history-v1', 'read-create': 'read-create-own-history-v1'}, create_enabled: true, connections: records, next_offset: null};
    const context = vm.createContext({
        document: {getElementById: field, createElement: element, addEventListener(name, fn) {handlers[name] = fn;}},
        window: {location: {origin: 'https://example.invalid'}, confirm: () => true,
            addEventListener(name, fn) {handlers[name] = fn;}},
        navigator: {clipboard: {writeText: async () => {}}},
        localStorage: new Proxy({}, {get() {throw Error('Storage must not be used');}, set() {throw Error('Storage must not be used');}}),
        sessionStorage: new Proxy({}, {get() {throw Error('Storage must not be used');}}),
        console: {log() {throw Error('No logs');}, error() {throw Error('No logs');}},
        fetch: async (url, options) => {
            requests.push({url, options});
            if (fail) throw new Error(token);
            const isPost = options.method === 'POST';
            return {ok: !isPost || postStatus === 201, status: isPost ? postStatus : 200,
                json: async () => isPost ? {id: 'synthetic-grant', token, client_id: 'rook', scopes: JSON.parse(options.body).access === 'read-create' ? ['tips:read', 'tips:create'] : ['tips:read'], expires_at: 2000000000} : state};
        }
    });
    vm.runInContext(source, context);
    field('clientId').value = 'rook';
    field('expiryHours').value = '24';
    field('accessLevel').value = 'read';
    return {context, field, requests, handlers, token};
}

test('opening the page only verifies/lists; consent is required to issue', async () => {
    const s = setup();
    await s.context.loadConnections();
    await s.context.issueConnection({preventDefault() {}});
    assert.equal(s.requests.length, 1);
    assert.equal(s.requests[0].url, '/api/integration-access');
    assert.equal(s.requests[0].options.credentials, 'same-origin');
    assert.equal(s.requests[0].options.cache, 'no-store');
    assert.equal(s.field('accessAccount').textContent, 'synthetic@example.invalid');
});

test('explicit issuance uses the displayed scope/expiry consent and reveals only in memory', async () => {
    const s = setup();
    await s.context.loadConnections();
    s.field('readConsent').checked = true;
    await s.context.issueConnection({preventDefault() {}});
    const post = s.requests.find(r => r.options.method === 'POST');
    assert.deepEqual(JSON.parse(post.options.body), {client_id: 'rook', expires_in_hours: 24, access: 'read',
        consent: 'read-only-own-history-v1', issuance_id: 'synthetic-issuance'});
    assert.equal(post.options.headers['X-CSRF-Token'], 'synthetic-csrf');
    assert.equal(s.field('issuedToken').value, s.token);
    assert.equal(s.field('tokenReveal').hidden, false);
    assert.equal(s.field('readConsent').checked, false);
    s.handlers.pagehide();
    assert.equal(s.field('issuedToken').value, '');
    assert.equal(s.field('tokenReveal').hidden, true);
});

test('double-click cannot issue two credentials', async () => {
    const s = setup();
    await s.context.loadConnections();
    s.field('readConsent').checked = true;
    await Promise.all([s.context.issueConnection({preventDefault() {}}), s.context.issueConnection({preventDefault() {}})]);
    assert.equal(s.requests.filter(r => r.options.method === 'POST').length, 1);
});

for (const postStatus of [401, 403, 409, 503]) {
    test(`HTTP ${postStatus} does not expose a token or retry issuance`, async () => {
        const s = setup({postStatus});
        await s.context.loadConnections();
        s.field('readConsent').checked = true;
        await s.context.issueConnection({preventDefault() {}});
        assert.equal(s.field('issuedToken').value, '');
        assert.equal(s.requests.filter(r => r.options.method === 'POST').length, 1);
        assert.equal(s.field('connectionSetup').hidden, true);
        assert.ok(!s.field('accessStatus').textContent.includes(s.token));
    });
}

test('network errors hide stale access and do not expose exception details', async () => {
    const s = setup({fail: true});
    s.field('issuedToken').value = s.token;
    await s.context.loadConnections();
    assert.equal(s.field('issuedToken').value, '');
    assert.equal(s.field('connectionSetup').hidden, true);
    assert.ok(!s.field('accessStatus').textContent.includes(s.token));
});

test('revocation requires a separate explicit confirmation', async () => {
    const record = {id: 'synthetic-grant', client_id: 'rook', scopes: ['tips:read'], expires_at: 2000000000, revoked: false};
    const s = setup({records: [record]});
    await s.context.loadConnections();
    const revoke = s.field('connectionList').children[0].children[1];
    s.context.window.confirm = () => false;
    await revoke.listeners.click();
    assert.equal(s.requests.filter(r => r.options.method === 'POST').length, 0);
    s.context.window.confirm = () => true;
    await revoke.listeners.click();
    assert.equal(s.requests.filter(r => r.options.method === 'POST').length, 1);
    const post = s.requests.find(r => r.options.method === 'POST');
    assert.deepEqual(JSON.parse(post.options.body), {revoke: true});
});


test('read-and-create is an explicit choice with distinct consent and visible permissions', async () => {
    const s = setup();
    await s.context.loadConnections();
    s.field('readConsent').checked = true;
    s.field('accessLevel').value = 'read-create';
    s.context.updateConsent();
    assert.equal(s.field('readConsent').checked, false);
    assert.equal(s.field('creationDetails').hidden, false);
    assert.ok(s.field('consentText').textContent.includes('approve each exact preview'));
    s.field('readConsent').checked = true;
    await s.context.issueConnection({preventDefault() {}});
    const body = JSON.parse(s.requests.find(r => r.options.method === 'POST').options.body);
    assert.equal(body.access, 'read-create');
    assert.equal(body.consent, 'read-create-own-history-v1');
    assert.equal(s.field('issuedScopes').textContent, 'tips:read, tips:create');
});
