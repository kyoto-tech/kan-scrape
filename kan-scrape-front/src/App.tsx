import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { useRef, useState } from 'react'

gsap.registerPlugin(useGSAP)

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
  const appRef = useRef<HTMLElement | null>(null)
  const titleRef = useRef<HTMLHeadingElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)

  useGSAP(
    () => {
      const reduceMotion = window.matchMedia(
        '(prefers-reduced-motion: reduce)',
      ).matches

      if (reduceMotion) return

      const intro = gsap.timeline({ defaults: { ease: 'power3.out' } })
      intro.from(titleRef.current, {
        autoAlpha: 0,
        y: -32,
        duration: 0.75,
      })
      intro.from(
        buttonRef.current,
        {
          autoAlpha: 0,
          scale: 0.35,
          duration: 0.9,
          ease: 'back.out(1.7)',
        },
        '-=0.3',
      )
    },
    { scope: appRef },
  )

  const startListening = () => {
    if (isListening) return

    const Recognition =
      window.SpeechRecognition ?? window.webkitSpeechRecognition

    if (!Recognition) {
      setMessage('Speech input is not supported in this browser.')
      return
    }

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

  const toggleListening = () => {
    if (isListening) {
      void stopListening()
      return
    }

    startListening()
  }

  return (
    <main ref={appRef} className="app-shell">
      <h1 ref={titleRef}>Kyoto Meetup Finder</h1>
      <button
        ref={buttonRef}
        className={`talk-button${isListening ? ' is-listening' : ''}`}
        type="button"
        aria-pressed={isListening}
        aria-label={isListening ? 'Stop listening and send' : 'Start listening'}
        onClick={toggleListening}
      >
        <span aria-hidden="true" className="talk-button__dot" />
        {isListening ? 'Stop and search' : 'Start speaking'}
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
