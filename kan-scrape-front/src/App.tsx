import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { GooeyToaster, gooeyToast } from 'goey-toast'
import { useRef, useState } from 'react'
import 'goey-toast/styles.css'

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

type MeetupEvent = {
  date: string
  category: string
  title: string
  location: string
  time: string
  description: string
}

const DEMO_EVENTS: MeetupEvent[] = [
  {
    date: 'AUG 29',
    category: 'TECH & COFFEE',
    title: 'Morning Tech & Coffee',
    location: 'Starbucks Karasuma Shijo',
    time: '09:30–10:30',
    description:
      'A relaxed, conversation-first meetup for builders, designers, and curious minds.',
  },
  {
    date: 'SEP 12',
    category: 'HACK DAY',
    title: 'Community Hack Day',
    location: 'FabCafe Kyoto MTRL/KYOTO',
    time: '12:00–17:00',
    description:
      'Bring an idea, a side project, or just your curiosity and build alongside the community.',
  },
  {
    date: 'SEP 17',
    category: 'TECH & COFFEE',
    title: 'Morning Tech & Coffee',
    location: 'Starbucks Karasuma Shijo',
    time: '08:30–09:30',
    description:
      'Start the day with an easy-going conversation about technology and life in Kyoto.',
  },
]

function App() {
  const [isListening, setIsListening] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [events, setEvents] = useState<MeetupEvent[]>([])
  const recognitionRef = useRef<Recognition | null>(null)
  const transcriptRef = useRef('')
  const appRef = useRef<HTMLElement | null>(null)
  const titleRef = useRef<HTMLHeadingElement | null>(null)
  const introRef = useRef<HTMLParagraphElement | null>(null)
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
        duration: 1.35,
      })
      intro.from(
        introRef.current,
        {
          autoAlpha: 0,
          y: -18,
          duration: 1.1,
          ease: 'power2.out',
        },
        '-=0.8',
      )
      intro.from(
        buttonRef.current,
        {
          autoAlpha: 0,
          filter: 'blur(16px)',
          duration: 1.8,
          ease: 'power2.out',
          clearProps: 'filter',
        },
        '-=0.55',
      )
    },
    { scope: appRef },
  )

  const startListening = () => {
    if (isListening) return

    const Recognition =
      window.SpeechRecognition ?? window.webkitSpeechRecognition

    if (!Recognition) {
      gooeyToast.error('Speech input unavailable', {
        description: 'Try a browser with microphone speech recognition enabled.',
        fillColor: '#B83230',
        borderColor: '#8F2624',
      })
      return
    }

    transcriptRef.current = ''

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
      gooeyToast.error('We could not hear that', {
        description: 'Try again and speak clearly into your microphone.',
        fillColor: '#B83230',
        borderColor: '#8F2624',
      })
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
      gooeyToast.info('Nothing to search yet', {
        description: 'Speak into the microphone before stopping the search.',
      })
      return
    }

    setIsSearching(true)
    try {
      // Demo response until the backend endpoint is connected.
      await new Promise((resolve) => window.setTimeout(resolve, 1400))
      setEvents(DEMO_EVENTS)
      gooeyToast.success('Meetups found', {
        description: 'Here are a few events matching your request.',
        fillColor: '#0F172A',
        borderColor: '#334155',
      })
    } catch {
      gooeyToast.error('Search failed', {
        description: 'The meetup search could not be completed. Try again.',
        fillColor: '#B83230',
        borderColor: '#8F2624',
      })
    } finally {
      setIsSearching(false)
    }
  }

  const toggleListening = () => {
    if (isSearching) return

    if (isListening) {
      void stopListening()
      return
    }

    startListening()
  }

  return (
    <main ref={appRef} className="app-shell">
      <GooeyToaster position="top-right" />
      <h1 ref={titleRef}>Kyoto Meetup Finder</h1>
      <p ref={introRef} className="intro">
        Speak into the microphone to find the best meetup events.
      </p>
      <button
        ref={buttonRef}
        className={`talk-button${isListening ? ' is-listening' : ''}${isSearching ? ' is-searching' : ''}`}
        type="button"
        aria-pressed={isListening}
        aria-busy={isSearching}
        aria-label={
          isSearching
            ? 'Searching for meetups'
            : isListening
              ? 'Stop listening and send'
              : 'Start listening'
        }
        disabled={isSearching}
        onClick={toggleListening}
      >
        {isSearching ? (
          <span aria-hidden="true" className="talk-button__loader" />
        ) : (
          <span aria-hidden="true" className="talk-button__dot" />
        )}
        {isSearching
          ? 'Searching…'
          : isListening
            ? 'Stop and search'
            : 'Start speaking'}
      </button>
      {events.length > 0 && (
        <section className="results-panel" aria-live="polite">
          <div className="results-heading">
            <span>Curated for Kyoto</span>
            <span>{events.length} events</span>
          </div>
          <div className="event-list">
            {events.map((event) => (
              <article className="event-card" key={`${event.date}-${event.title}`}>
                <div className="event-card__date">{event.date}</div>
                <div className="event-card__content">
                  <p className="event-card__category">{event.category}</p>
                  <h2>{event.title}</h2>
                  <p className="event-card__meta">
                    {event.location} · {event.time}
                  </p>
                  <p className="event-card__description">{event.description}</p>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </main>
  )
}

export default App
