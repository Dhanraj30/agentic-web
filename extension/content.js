// AgenticWeb - Content Script
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === 'GET_PAGE') {
    const clone = document.body.cloneNode(true)
    clone.querySelectorAll('script,style,nav,footer,iframe').forEach(e => e.remove())
    reply({ url: location.href, title: document.title, text: (clone.innerText || '').replace(/\s+/g, ' ').slice(0, 2000) })
    return true
  }
})
