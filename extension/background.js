// AgenticWeb Extension — Background Service Worker
const AGENT = 'http://localhost:8765'

chrome.action.onClicked.addListener(tab => chrome.sidePanel.open({ windowId: tab.windowId }))

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === 'RUN_GOAL')     { runGoal(msg.goal, msg.provider); reply({ ok: true }); return true }
  if (msg.type === 'GET_SETTINGS') { chrome.storage.local.get(['provider'], reply); return true }
  if (msg.type === 'SAVE_SETTINGS'){ chrome.storage.local.set({ provider: msg.provider }, () => reply({ ok: true })); return true }
  if (msg.type === 'GET_PROVIDERS'){ fetch(`${AGENT}/providers`).then(r=>r.json()).then(reply).catch(e=>reply({error:e.message})); return true }
})

async function runGoal(goal, provider) {
  broadcast({ type: 'TASK_START', goal })
  try {
    const settings = await chrome.storage.local.get(['provider'])
    const p = provider || settings.provider || 'gemini'
    const resp = await fetch(`${AGENT}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, provider: p }),
    })
    if (!resp.ok) { broadcast({ type: 'ERROR', message: `Agent error: ${resp.status}` }); return }
    const reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { broadcast({ type: 'AGENT_EVENT', event: JSON.parse(line.slice(6)) }) } catch (_) {}
        }
      }
    }
  } catch (e) {
    broadcast({ type: 'ERROR', message: `Cannot reach agent at ${AGENT}. Run ./scripts/start.sh` })
  }
}

function broadcast(msg) { chrome.runtime.sendMessage(msg).catch(() => {}) }
