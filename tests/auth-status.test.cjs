const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(resolve(__dirname, '../static/js/app.js'), 'utf8');
const session = {
    access_token: 'synthetic-token-not-for-logging',
    user: { id: 'test-user', email: 'test@example.invalid', user_metadata: { name: 'Test' } }
};

function setup({ status = 200, sessionResult = { data: { session } }, networkError = false } = {}) {
    const calls = { requests: [], alerts: [], logs: [], roles: 0, dashboards: 0 };
    const elements = new Map();
    const context = vm.createContext({
        document: {
            addEventListener() {},
            getElementById(id) {
                if (!elements.has(id)) {
                    const classes = new Set();
                    elements.set(id, {
                        textContent: '',
                        classList: {
                            add: value => classes.add(value),
                            remove: value => classes.delete(value),
                            contains: value => classes.has(value)
                        }
                    });
                }
                return elements.get(id);
            }
        },
        supabase: { auth: { getSession: async () => sessionResult } },
        fetch: async (url, options) => {
            calls.requests.push({ url, options });
            if (networkError) throw new Error(session.access_token);
            return {
                ok: status >= 200 && status < 300,
                status,
                json: async () => ({ id: 'server-user', name: 'Server User' })
            };
        },
        console: {
            error: (...args) => calls.logs.push(args),
            log: (...args) => calls.logs.push(args)
        }
    });
    vm.runInContext(source, context);
    context.loadPublicDashboard = () => {};
    context.loadUserRole = async () => { calls.roles++; };
    context.loadDashboard = () => { calls.dashboards++; };
    context.showAlert = (...args) => calls.alerts.push(args);
    // Start from a previously signed-in view to catch stale state on failure.
    vm.runInContext('currentUser = { id: "previous-user" }; showMainApp();', context);
    return { context, calls, elements };
}

function assertSignedOut({ context, calls, elements }, alertCount = 1) {
    assert.equal(vm.runInContext('currentUser', context), null);
    assert.equal(elements.get('mainApp').classList.contains('d-none'), true);
    assert.equal(elements.get('authRequired').classList.contains('d-none'), false);
    assert.equal(elements.get('loginBtn').classList.contains('d-none'), false);
    assert.equal(elements.get('userSection').classList.contains('d-none'), true);
    assert.equal(calls.roles, 0);
    assert.equal(calls.dashboards, 0);
    assert.equal(calls.alerts.length, alertCount);
    assert.equal(JSON.stringify([calls.alerts, calls.logs]).includes(session.access_token), false);
}

for (const status of [400, 401, 403, 500, 503]) {
    test(`session sync HTTP ${status} leaves the user signed out without fallback`, async () => {
        const app = setup({ status });
        await app.context.checkAuthStatus();
        assertSignedOut(app);
        assert.deepEqual(app.calls.requests.map(r => r.url), ['/auth/session']);
        assert.match(app.calls.alerts[0][0], status === 401 || status === 403 ? /rejected/ : /try again later/);
    });
}

test('session sync network failure is safe and does not load private data', async () => {
    const app = setup({ networkError: true });
    await app.context.checkAuthStatus();
    assertSignedOut(app);
    assert.equal(app.calls.requests.length, 1);
});

test('Supabase session errors do not silently fall back to a server session', async () => {
    const app = setup({ sessionResult: { data: { session }, error: new Error(session.access_token) } });
    await app.context.checkAuthStatus();
    assertSignedOut(app);
    assert.equal(app.calls.requests.length, 0);
});

test('successful sync sends the token and opens the dashboard', async () => {
    const app = setup();
    await app.context.checkAuthStatus();
    assert.equal(vm.runInContext('currentUser.id', app.context), session.user.id);
    assert.equal(app.calls.requests[0].options.method, 'POST');
    assert.equal(JSON.parse(app.calls.requests[0].options.body).access_token, session.access_token);
    assert.equal(app.elements.get('mainApp').classList.contains('d-none'), false);
    assert.equal(app.calls.roles, 1);
    assert.equal(app.calls.dashboards, 1);
    assert.equal(app.calls.alerts.length, 0);
});

for (const status of [200, 401, 503]) {
    test(`without a Supabase session, server session HTTP ${status} is handled`, async () => {
        const app = setup({ status, sessionResult: { data: { session: null } } });
        await app.context.checkAuthStatus();
        assert.deepEqual(app.calls.requests.map(r => r.url), ['/auth/user']);
        if (status === 200) {
            assert.equal(vm.runInContext('currentUser.id', app.context), 'server-user');
            assert.equal(app.calls.dashboards, 1);
        } else {
            assertSignedOut(app, status === 401 ? 0 : 1);
        }
    });
}
