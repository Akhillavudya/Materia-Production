import { useState } from 'react'
import Sidebar    from './Sidebar'
import Chat       from './Chat'
import RightPanel from './RightPanel'
import { fetchMessages } from './api'

export default function App() {
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [loadedMessages,  setLoadedMessages]  = useState([])
  const [filePanelRefresh, setFilePanelRefresh] = useState(0)
  const [jobRefresh,       setJobRefresh]       = useState(0)
  const [rerunMessage,     setRerunMessage]     = useState(null)

  async function handleSelectSession(id) {
    if (id === activeSessionId) return
    setFilePanelRefresh(0)
    setJobRefresh(0)
    try {
      const msgs = await fetchMessages(id)
      setLoadedMessages(msgs)
    } catch {
      setLoadedMessages([])
    }
    setActiveSessionId(id)
  }

  function handleNewChat() {
    setActiveSessionId(null)
    setLoadedMessages([])
    setFilePanelRefresh(0)
    setJobRefresh(0)
    setRerunMessage(null)
  }

  function handleSessionCreated(id) { setActiveSessionId(id) }
  function handleFilesGenerated()   { setFilePanelRefresh(p => p + 1) }
  function handleJobDone()          { setJobRefresh(p => p + 1) }
  function handleRerun(msg)         { setRerunMessage(msg) }
  function handleRerunConsumed()    { setRerunMessage(null) }

  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      overflow: 'hidden',
      background: 'var(--bg-page)',
    }}>
      <Sidebar
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
      />

      <Chat
        sessionId={activeSessionId}
        initialMessages={loadedMessages}
        onSessionCreated={handleSessionCreated}
        onFilesGenerated={handleFilesGenerated}
        onJobDone={handleJobDone}
        rerunMessage={rerunMessage}
        onRerunConsumed={handleRerunConsumed}
      />

      <RightPanel
        sessionId={activeSessionId}
        filePanelRefresh={filePanelRefresh}
        jobRefresh={jobRefresh}
        onRerun={handleRerun}
      />
    </div>
  )
}

// import { useState } from 'react'
// import Sidebar   from './Sidebar'
// import Chat      from './Chat'
// import FilePanel from './FilePanel'
// import { fetchMessages } from './api'

// export default function App() {
//   const [activeSessionId,   setActiveSessionId]   = useState(null)
//   const [loadedMessages,    setLoadedMessages]    = useState([])

//   // increment this after every tool call → FilePanel auto-reloads
//   const [filePanelRefresh,  setFilePanelRefresh]  = useState(0)

//   async function handleSelectSession(id) {
//     if (id === activeSessionId) return
//     setActiveSessionId(id)
//     setFilePanelRefresh(0)   // reset refresh counter for new session
//     try {
//       const msgs = await fetchMessages(id)
//       setLoadedMessages(msgs)
//     } catch {
//       setLoadedMessages([])
//     }
//   }

//   function handleNewChat() {
//     setActiveSessionId(null)
//     setLoadedMessages([])
//     setFilePanelRefresh(0)
//   }

//   function handleSessionCreated(id) {
//     setActiveSessionId(id)
//   }

//   // called by Chat whenever a [FILES:...] event arrives
//   function handleFilesGenerated() {
//     setFilePanelRefresh(prev => prev + 1)
//   }

//   return (
//     <div style={{
//       display: 'flex',
//       height: '100vh',
//       background: '#0f1117',
//       overflow: 'hidden',
//     }}>
//       <Sidebar
//         activeSessionId={activeSessionId}
//         onSelectSession={handleSelectSession}
//         onNewChat={handleNewChat}
//       />

//       <Chat
//         key={activeSessionId}
//         sessionId={activeSessionId}
//         initialMessages={loadedMessages}
//         onSessionCreated={handleSessionCreated}
//         onFilesGenerated={handleFilesGenerated}   
//       />

//       <FilePanel
//         sessionId={activeSessionId}
//         refreshTrigger={filePanelRefresh}
//       />
//     </div>
//   )
// }

// // import { useState } from 'react'
// // import Sidebar from './Sidebar'
// // import Chat    from './Chat'
// // import { fetchMessages } from './api'

// // export default function App() {
// //   const [activeSessionId, setActiveSessionId] = useState(null)
// //   const [loadedMessages,  setLoadedMessages]  = useState([])

// //   async function handleSelectSession(id) {
// //     if (id === activeSessionId) return
// //     setActiveSessionId(id)
// //     try {
// //       const msgs = await fetchMessages(id)
// //       setLoadedMessages(msgs)
// //     } catch {
// //       setLoadedMessages([])
// //     }
// //   }

// //   function handleNewChat() {
// //     setActiveSessionId(null)
// //     setLoadedMessages([])
// //   }

// //   function handleSessionCreated(id) {
// //     setActiveSessionId(id)
// //     // Chat already has the messages locally — no need to reload
// //   }

// //   return (
// //     <div style={{ display: 'flex', height: '100vh', background: '#0f1117', overflow: 'hidden' }}>
// //       <Sidebar
// //         activeSessionId={activeSessionId}
// //         onSelectSession={handleSelectSession}
// //         onNewChat={handleNewChat}
// //       />
// //       <Chat
// //         key={activeSessionId}
// //         sessionId={activeSessionId}
// //         initialMessages={loadedMessages}
// //         onSessionCreated={handleSessionCreated}
// //       />
// //     </div>
// //   )
// // }


// // //import Chat from './Chat'

// // export default function App() {
// //   return <Chat />
// // }
