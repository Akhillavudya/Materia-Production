import { useState, useRef, useEffect } from 'react'
import { streamChat } from '../../api'
import FileCard    from '../files/FileCard'
import ToolStatus  from './ToolStatus'
import ApiKeyForm  from './ApiKeyForm'
import UploadButton from './UploadButton'
import { LogoMark } from '../../components/Logo'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'


function normalizeMathDelimiters(content) {
  return content
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map(segment => {
      if (segment.startsWith('`')) return segment
      return segment
        .replace(/\\\[/g, '$$')
        .replace(/\\\]/g, '$$')
        .replace(/\\\(/g, '$')
        .replace(/\\\)/g, '$')
    })
    .join('')
}

function AssistantMarkdown({ content }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath, remarkBreaks]}
      rehypePlugins={[rehypeKatex]}
      components={{
        a: ({ children, ...props }) => (
          <a {...props} target="_blank" rel="noreferrer">{children}</a>
        ),
        code: ({ children, className, ...props }) => {
          const codeText = String(children)
          const isInline = !className && !codeText.includes('\n')
          return (
            <code
              {...props}
              className={isInline ? 'assistant-inline-code' : className}
            >
              {children}
            </code>
          )
        },
      }}
    >
      {normalizeMathDelimiters(content)}
    </ReactMarkdown>
  )
}

const SUGGESTIONS = [
  'Generate POSCAR for NaCl',
  'Run EOS calculation using CHGNet',
  'Create a 2×2×2 supercell',
  'Optimize crystal structure with MLP',
]

// ── helper: create a blank assistant message slot ─────────────────────────────
function blankAssistant() {
  return {
    role:        'assistant',
    content:     '',
    // toolCards is the KEY change — array so multiple tool results accumulate
    // each entry: { toolName, status, files, label }
    toolCards:   [],
    // the currently-running tool (shows spinner) — cleared when TOOL_END arrives
    activeToolName:   null,
    activeToolStatus: 'running',
    statusText:  '',         // transient "🧠 Planning…" label, cleared on DONE
    needsApiKey: null,
  }
}

function timeGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

export default function Chat({
  sessionId,
  userName,
  initialMessages,
  onSessionCreated,
  onFilesGenerated,
  onJobDone,
  rerunMessage,
  onRerunConsumed,
}) {
  const [messages,  setMessages]  = useState(initialMessages || [])
  const [input,     setInput]     = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error,     setError]     = useState(null)
  const [pendingMessage, setPendingMessage] = useState(null)

  const bottomRef   = useRef(null)
  const textareaRef = useRef(null)
  const abortControllerRef = useRef(null)
  const mountedRef = useRef(true)
  const previousSessionRef = useRef(sessionId)
  const sendMessageRef = useRef(null)
  const onRerunConsumedRef = useRef(onRerunConsumed)

  useEffect(() => {
    const sessionChanged = sessionId !== previousSessionRef.current
    previousSessionRef.current = sessionId
    setMessages(prev => {
      const incoming = initialMessages || []
      if (sessionChanged && incoming.length === 0 && prev.length > 0) {
        return prev
      }
      return incoming
    })
    setInput('')
    setError(null)
  }, [sessionId, initialMessages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])


  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortControllerRef.current?.abort()
    }
  }, [])

  function resizeTextarea() {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 180) + 'px'
  }

  // ── shared updater: always patches the last message ───────────────────────
  function patchLast(patchFn) {
    setMessages(prev => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      if (!last) return prev
      copy[copy.length - 1] = patchFn(last)
      return copy
    })
  }

  async function sendMessage(overrideText) {
    const text = (overrideText || input).trim()
    if (!text || streaming) return
    const controller = new AbortController()
    abortControllerRef.current = controller

    setError(null)
    setInput('')
    setTimeout(resizeTextarea, 0)

    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      blankAssistant(),
    ])
    setStreaming(true)

    await streamChat(
      sessionId,
      text,

      // onToken — append to assistant text
      (token) => {
        if (!mountedRef.current) return
        patchLast(last => ({ ...last, content: last.content + token }))
      },

      // onSessionId
      (id) => {
        if (!mountedRef.current) return
        onSessionCreated(id)
      },

      // onFiles — push a new completed tool card into the array
      (fileData) => {
        if (!mountedRef.current) return
        patchLast(last => ({
          ...last,
          // replace the active (running) card with completed version,
          // or append if somehow we get FILES without a prior TOOL_START
          toolCards: last.activeToolName
            ? [
                ...last.toolCards.filter(c => c.toolName !== last.activeToolName),
                {
                  toolName: fileData.tool   || last.activeToolName,
                  label:    fileData.label  || last.activeToolName,
                  status:   fileData.status || 'success',
                  files:    fileData.files  || [],
                },
              ]
            : [
                ...last.toolCards,
                {
                  toolName: fileData.tool,
                  label:    fileData.label,
                  status:   fileData.status,
                  files:    fileData.files || [],
                },
              ],
          activeToolName: null,   // spinner is done
        }))
        onFilesGenerated?.()
      },

      // onToolStart — add a new "running" card and set it as active
      (toolName) => {
        if (!mountedRef.current) return
        patchLast(last => ({
          ...last,
          activeToolName:   toolName,
          activeToolStatus: 'running',
          // add placeholder card immediately so spinner appears right away
          toolCards: [
            ...last.toolCards,
            { toolName, label: toolName, status: 'running', files: [] },
          ],
        }))
      },

      // onToolEnd — update the matching card's status
      (toolName, status) => {
        if (!mountedRef.current) return
        patchLast(last => ({
          ...last,
          activeToolName:   last.activeToolName === toolName ? null : last.activeToolName,
          activeToolStatus: status,
          toolCards: last.toolCards.map(c =>
            c.toolName === toolName && c.status === 'running'
              ? { ...c, status }
              : c
          ),
        }))
      },

      // onStatus — show transient planning/progress label (NEVER in chat text)
      (statusText) => {
        if (!mountedRef.current) return
        patchLast(last => ({ ...last, statusText: statusText || '' }))
      },

      // onNeedApiKey
      (service) => {
        if (!mountedRef.current) return
        setPendingMessage(text)
        patchLast(last => ({ ...last, needsApiKey: service }))
      },

      // onJobDone
      () => {
        if (!mountedRef.current) return
        onJobDone?.()
      },

      // onDone
      () => {
        if (!mountedRef.current) return
        abortControllerRef.current = null
        patchLast(last => ({ ...last, statusText: '', activeToolName: null }))
        setStreaming(false)
      },

      // onError
      (err) => {
        if (!mountedRef.current) return
        abortControllerRef.current = null
        setError(err)
        setStreaming(false)
      },
      {
        signal: controller.signal,
        onAbort: () => {
          if (!mountedRef.current) return
          patchLast(last => ({
            ...last,
            content: last.content
              ? `${last.content}\n\n_Generation stopped._`
              : '_Generation stopped._',
            statusText: '',
            activeToolName: null,
            toolCards: last.toolCards.map(card =>
              card.status === 'running' ? { ...card, status: 'canceled' } : card
            ),
          }))
          abortControllerRef.current = null
          setStreaming(false)
        },
      }
    )
  }

  useEffect(() => {
    sendMessageRef.current = sendMessage
    onRerunConsumedRef.current = onRerunConsumed
  })

  useEffect(() => {
    if (!rerunMessage) return
    sendMessageRef.current?.(rerunMessage)
    onRerunConsumedRef.current?.()
  }, [rerunMessage])

  function stopGeneration() {
    abortControllerRef.current?.abort()
  }

  async function handleKeySaved() {
    if (!pendingMessage) return
    const retry = pendingMessage
    setPendingMessage(null)
    await new Promise(r => setTimeout(r, 600))
    sendMessage(retry)
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  function handleUploadDone(sid, uploadedFiles, activation) {
    onFilesGenerated?.()
    if (sid !== sessionId) onSessionCreated?.(sid)

    if (uploadedFiles && uploadedFiles.length > 0) {
      const names = uploadedFiles.map(f => f.name).join(', ')

      // Phase E (U1): the backend tells us what it did with the structure(s).
      let tail = ''
      switch (activation?.status) {
        case 'activated':
          tail = `\n\n**${activation.formula}** (${activation.n_sites} atoms) is now the active structure. ` +
                 `You can generate VASP inputs, build supercells, add defects, or run an MLP simulation.`
          break
        case 'multiple':
          tail = `\n\nYou uploaded ${activation.candidates.length} structures ` +
                 `(${activation.candidates.join(', ')}). **Which one should I make active?**`
          break
        case 'unreadable':
          tail = `\n\nI couldn't parse **${activation.file}** as a crystal structure, so nothing was activated. ` +
                 `${activation.error || ''}`
          break
        default:
          tail = ''
      }

      setMessages(prev => [
        ...prev,
        { ...blankAssistant(), content: `✓ Uploaded: **${names}**${tail}` },
      ])
    }
  }

  const canSend = input.trim().length > 0 && !streaming
  const isEmpty = messages.length === 0
  const firstName = (userName || '').trim().split(/[\s@]/)[0]

  // The composer "pill" is reused in two places: centered on the new-chat
  // welcome screen, and pinned to the bottom once a conversation is going.
  const composer = (
    <div style={{
      display: 'flex', alignItems: 'flex-end', gap: '0',
      background: '#ffffff', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-xl)', padding: '10px 10px 10px 16px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.06)', transition: 'border-color 0.15s, box-shadow 0.15s',
    }}
    onFocusCapture={e => {
      e.currentTarget.style.borderColor = '#a5b4fc'
      e.currentTarget.style.boxShadow = '0 2px 12px rgba(99,102,241,0.12)'
    }}
    onBlurCapture={e => {
      e.currentTarget.style.borderColor = 'var(--border)'
      e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)'
    }}
    >
      <UploadButton
        sessionId={sessionId}
        onUploadDone={handleUploadDone}
        onSessionCreated={onSessionCreated}
        disabled={streaming}
      />

      <textarea
        ref={textareaRef}
        value={input}
        onChange={e => { setInput(e.target.value); resizeTextarea() }}
        onKeyDown={handleKeyDown}
        placeholder="Message Materia..."
        rows={1}
        disabled={streaming}
        style={{
          flex: 1, resize: 'none', border: 'none', outline: 'none',
          background: 'transparent', fontSize: '15px', lineHeight: '1.5',
          color: 'var(--text-primary)', fontFamily: 'var(--font)',
          minHeight: '24px', maxHeight: '180px', overflowY: 'auto', padding: '2px 0',
        }}
      />

      <button
        onClick={streaming ? stopGeneration : () => sendMessage()}
        disabled={!streaming && !canSend}
        title={streaming ? 'Stop generation' : 'Send message'}
        style={{
        width: '34px', height: '34px', borderRadius: '50%',
        background: streaming ? '#111827' : canSend ? '#6366f1' : 'var(--border)', border: 'none',
        color: streaming || canSend ? '#ffffff' : 'var(--text-muted)',
        cursor: streaming || canSend ? 'pointer' : 'not-allowed',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: streaming ? '10px' : '16px', flexShrink: 0, transition: 'all 0.15s',
        transform: streaming || canSend ? 'scale(1)' : 'scale(0.95)',
      }}>
        {streaming ? '■' : '↑'}
      </button>
    </div>
  )

  const suggestionChips = (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'center' }}>
      {SUGGESTIONS.map(chip => (
        <button key={chip} onClick={() => sendMessage(chip)} style={{
          padding: '9px 16px', background: '#ffffff',
          border: '1px solid var(--border)', borderRadius: '20px',
          fontSize: '13px', color: 'var(--text-secondary)',
          cursor: 'pointer', fontFamily: 'var(--font)', transition: 'all 0.15s',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.background = 'var(--hover-bg)'
          e.currentTarget.style.borderColor = '#d1cec7'
          e.currentTarget.style.color = 'var(--text-primary)'
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = '#ffffff'
          e.currentTarget.style.borderColor = 'var(--border)'
          e.currentTarget.style.color = 'var(--text-secondary)'
        }}
        >{chip}</button>
      ))}
    </div>
  )

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      overflow: 'hidden',
      background: 'var(--bg-chat)',
    }}>

      {/* ── top header bar ── */}
      <div style={{
        padding: '14px 24px',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
        background: 'var(--bg-chat)',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: '6px',
          fontSize: '15px', fontWeight: '500', color: 'var(--text-primary)',
        }}>
          Materials simulation assistant
          <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>∨</span>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {['↑', '···'].map(icon => (
            <button key={icon} style={{
              background: 'none', border: '1px solid var(--border)',
              borderRadius: '8px', width: '32px', height: '32px',
              cursor: 'pointer', fontSize: '14px',
              color: 'var(--text-muted)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'background 0.1s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
            onMouseLeave={e => e.currentTarget.style.background = 'none'}
            >
              {icon}
            </button>
          ))}
        </div>
      </div>

      {/* ── message list ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '32px 0' }}>

        {/* new-chat welcome — centered greeting + composer (Claude-style) */}
        {isEmpty && (
          <div style={{
            minHeight: '72vh', display: 'flex', flexDirection: 'column',
            justifyContent: 'center', alignItems: 'center',
            maxWidth: '720px', margin: '0 auto', padding: '0 24px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '28px' }}>
              <LogoMark size={36} radius={10} />
              <h1 style={{
                fontSize: '30px', fontWeight: 600, color: 'var(--text-primary)',
                letterSpacing: '-0.02em', margin: 0,
              }}>
                {timeGreeting()}{firstName ? `, ${firstName}` : ''}
              </h1>
            </div>
            <div style={{ width: '100%' }}>{composer}</div>
            <div style={{ marginTop: '20px' }}>{suggestionChips}</div>
          </div>
        )}

        {/* messages */}
        <div style={{
          maxWidth: '760px', margin: '0 auto',
          padding: '0 40px',
          display: 'flex', flexDirection: 'column', gap: '24px',
        }}>
          {messages.map((msg, i) => {
            const isLive = streaming && i === messages.length - 1 && msg.role === 'assistant'

            return (
              <div key={i} className="fade-in" style={{
                display: 'flex', flexDirection: 'column',
                alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
              }}>

                {/* ── assistant message ── */}
                {msg.role === 'assistant' && (
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start', width: '100%' }}>

                    {/* avatar */}
                    <span style={{ marginTop: '2px', display: 'inline-flex', flexShrink: 0 }}>
                      <LogoMark size={28} radius={8} />
                    </span>

                    <div style={{ flex: 1, minWidth: 0 }}>

                      {/* ── transient status label (planning / fetching…) ── */}
                      {isLive && msg.statusText && (
                        <div style={{
                          fontSize: '13px',
                          color: 'var(--text-muted)',
                          marginBottom: '8px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}>
                          <span style={{
                            display: 'inline-block',
                            width: '10px', height: '10px',
                            borderRadius: '50%',
                            border: '2px solid var(--text-muted)',
                            borderTopColor: 'transparent',
                            animation: 'spin 0.8s linear infinite',
                          }} />
                          {msg.statusText}
                        </div>
                      )}

                      {/* ── assistant text (markdown) ── */}
                      {msg.content && (
                        <div className="assistant-markdown">
                          <AssistantMarkdown content={msg.content} />

                          {/* streaming cursor — only when no tools running */}
                          {isLive && !msg.activeToolName && msg.toolCards.length === 0 && (
                            <span style={{
                              display: 'inline-block', width: '2px', height: '16px',
                              background: 'var(--text-primary)', marginLeft: '2px',
                              verticalAlign: 'text-bottom',
                              animation: 'blink 1s step-end infinite',
                            }} />
                          )}
                        </div>
                      )}

                      {/* ── tool cards — one per tool, in order ── */}
                      {msg.toolCards.map((card, ci) => (
                        <div key={ci}>
                          {/* spinner card for running step */}
                          {(card.status === 'running' || card.status === 'canceled') && (
                            <ToolStatus
                              toolName={card.toolName}
                              status={card.status}
                            />
                          )}

                          {/* completed card with files */}
                          {card.status !== 'running' && card.status !== 'canceled' && (
                            <FileCard
                              toolName={card.toolName}
                              label={card.label}
                              status={card.status}
                              files={card.files}
                            />
                          )}
                        </div>
                      ))}

                      {/* api key form */}
                      {msg.needsApiKey && (
                        <ApiKeyForm
                          service={msg.needsApiKey}
                          onKeySaved={handleKeySaved}
                        />
                      )}
                    </div>
                  </div>
                )}

                {/* ── user message ── */}
                {msg.role === 'user' && (
                  <div style={{
                    maxWidth: '70%', padding: '12px 16px',
                    background: 'var(--accent-blue)',
                    borderRadius: '18px 18px 4px 18px',
                    fontSize: '15px', lineHeight: '1.6',
                    color: 'var(--text-primary)',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  }}>
                    {msg.content}
                  </div>
                )}
              </div>
            )
          })}

          {error && (
            <div style={{
              padding: '10px 14px', background: '#fef2f2',
              border: '1px solid #fecaca', borderRadius: 'var(--radius-md)',
              fontSize: '13px', color: '#b91c1c',
            }}>⚠ {error}</div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── input area (bottom — only once a conversation is going) ── */}
      {!isEmpty && (
        <div style={{
          padding: '16px 40px 24px', background: 'var(--bg-chat)',
          flexShrink: 0, maxWidth: '760px', width: '100%',
          margin: '0 auto', boxSizing: 'border-box',
        }}>
          {composer}
          <div style={{
            textAlign: 'center', marginTop: '8px',
            fontSize: '11px', color: 'var(--text-muted)',
          }}>Shift + Enter for new line</div>
        </div>
      )}

      {/* ── global keyframe for spinner ── */}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
