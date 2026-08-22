import { type KeyboardEvent, useRef, useState } from 'react'

type RecognitionResult = {
  isFinal: boolean
  0: { transcript: string }
}

type RecognitionEvent = Event & {
  results: ArrayLike<RecognitionResult>
}

type Recognition = {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((event: RecognitionEvent) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

type RecognitionConstructor = new () => Recognition

declare global {
  interface Window {
    SpeechRecognition?: RecognitionConstructor
    webkitSpeechRecognition?: RecognitionConstructor
  }
}

const BACKEND_ENDPOINT = '/api/scrape'

function App() {
  const [isListening, setIsListening] = useState(false)
  const [message, setMessage] = useState('')
  const [result, setResult] = useState('')
  const recognitionRef = useRef<Recognition | null>(null)
  const transcriptRef = useRef('')
  const activePointerRef = useRef(false)

  const startListening = () => {
    if (activePointerRef.current || isListening) return

    const Recognition =
      window.SpeechRecognition ?? window.webkitSpeechRecognition

    if (!Recognition) {
      setMessage('Speech input is not supported in this browser.')
      return
    }

    activePointerRef.current = true
    transcriptRef.current = ''
    setMessage('')

    const recognition = new Recognition()
    recognition.lang = 'en-US'
    recognition.interimResults = true
    recognition.continuous = true
    recognition.onresult = (event) => {
      transcriptRef.current = Array.from(event.results)
        .map((item) => item[0].transcript)
        .join(' ')
    }
    recognition.onerror = () => {
      setMessage('We could not hear that. Try again.')
      setIsListening(false)
    }
    recognition.onend = () => setIsListening(false)
    recognitionRef.current = recognition
    recognition.start()
    setIsListening(true)
  }

  const stopListening = async () => {
    if (!activePointerRef.current) return

    activePointerRef.current = false
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setIsListening(false)

    const transcript = transcriptRef.current.trim()
    if (!transcript) {
      setMessage('Hold the button and say something first.')
      return
    }

    setMessage('')
    try {
      const response = await fetch(BACKEND_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: transcript }),
      })

      if (!response.ok) throw new Error('Request failed')
      const payload = (await response.json()) as { result?: string }
      setResult(payload.result ?? '')
    } catch {
      setMessage('The request could not be sent. Try again.')
    }
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault()
      startListening()
    }
  }

  const handleKeyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault()
      void stopListening()
    }
  }

  return (
    <main className="app-shell">
      <button
        className={`talk-button${isListening ? ' is-listening' : ''}`}
        type="button"
        aria-label={isListening ? 'Release to send' : 'Hold to speak'}
        onPointerDown={startListening}
        onPointerUp={() => void stopListening()}
        onPointerCancel={() => void stopListening()}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
      >
        <span aria-hidden="true" className="talk-button__dot" />
        {isListening ? 'Listening…' : 'Hold to speak'}
      </button>
      {(message || result) && (
        <output className="response">
          {result || message}
        </output>
      )}
    </main>
  )
}

export default App
