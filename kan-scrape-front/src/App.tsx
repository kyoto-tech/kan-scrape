import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { Toaster, toast } from 'sonner'
import { useRef, useState, type CSSProperties } from 'react'

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
    date: 'Aug 29',
    category: 'Tech & Coffee',
    title: 'Morning Tech & Coffee',
    location: 'Starbucks Karasuma Shijo',
    time: '09:30–10:30',
    description:
      'A relaxed, conversation-first meetup for builders, designers, and curious minds.',
  },
  {
    date: 'Sep 12',
    category: 'Hack Day',
    title: 'Community Hack Day',
    location: 'FabCafe Kyoto MTRL/KYOTO',
    time: '12:00–17:00',
    description:
      'Bring an idea, a side project, or just your curiosity and build alongside the community.',
  },
  {
    date: 'Sep 17',
    category: 'Tech & Coffee',
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
  const [voiceLevel, setVoiceLevel] = useState(0)
  const [events, setEvents] = useState<MeetupEvent[]>([])
  const recognitionRef = useRef<Recognition | null>(null)
  const transcriptRef = useRef('')
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const microphoneStreamRef = useRef<MediaStream | null>(null)
  const meterFrameRef = useRef<number | null>(null)
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

  const stopVoiceMeter = () => {
    if (meterFrameRef.current !== null) {
      cancelAnimationFrame(meterFrameRef.current)
      meterFrameRef.current = null
    }

    microphoneStreamRef.current?.getTracks().forEach((track) => track.stop())
    microphoneStreamRef.current = null

    if (audioContextRef.current) {
      void audioContextRef.current.close()
      audioContextRef.current = null
    }

    analyserRef.current = null
    setVoiceLevel(0)
  }

  const startVoiceMeter = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const audioContext = new AudioContext()
    const analyser = audioContext.createAnalyser()
    const source = audioContext.createMediaStreamSource(stream)

    analyser.fftSize = 256
    const data = new Uint8Array(analyser.fftSize)
    source.connect(analyser)
    microphoneStreamRef.current = stream
    audioContextRef.current = audioContext
    analyserRef.current = analyser

    const measure = () => {
      if (!analyserRef.current) return

      analyserRef.current.getByteTimeDomainData(data)
      const sum = data.reduce((total, sample) => {
        const normalized = (sample - 128) / 128
        return total + normalized * normalized
      }, 0)
      const rms = Math.sqrt(sum / data.length)
      setVoiceLevel((current) => current * 0.65 + Math.min(rms * 3, 1) * 0.35)
      meterFrameRef.current = requestAnimationFrame(measure)
    }

    measure()
  }

  const startListening = async () => {
    if (isListening) return

    const Recognition =
      window.SpeechRecognition ?? window.webkitSpeechRecognition

    if (!Recognition) {
      toast.error('Speech input unavailable', {
        description: 'Try a browser with microphone speech recognition enabled.',
      })
      return
    }

    try {
      await startVoiceMeter()
    } catch {
      toast.error('Microphone access is needed', {
        description: 'Allow microphone access to show your voice level.',
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
      toast.error('We could not hear that', {
        description: 'Try again and speak clearly into your microphone.',
      })
      setIsListening(false)
      stopVoiceMeter()
    }
    recognition.onend = () => {
      setIsListening(false)
      stopVoiceMeter()
    }
    recognitionRef.current = recognition
    recognition.start()
    setIsListening(true)
  }

  const stopListening = async () => {
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setIsListening(false)
    stopVoiceMeter()

    const transcript = transcriptRef.current.trim()
    if (!transcript) {
      toast.info('Nothing to search yet', {
        description: 'Speak into the microphone before stopping the search.',
      })
      return
    }

    setIsSearching(true)
    try {
      // Demo response until the backend endpoint is connected.
      await new Promise((resolve) => window.setTimeout(resolve, 1400))
      setEvents(DEMO_EVENTS)
      toast.success('Meetups found', {
        description: 'Here are a few events matching your request.',
      })
    } catch {
      toast.error('Search failed', {
        description: 'The meetup search could not be completed. Try again.',
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

    void startListening()
  }

  return (
    <main ref={appRef} className="app-shell">
      <Toaster
        position="top-right"
        theme="light"
        richColors
        toastOptions={{
          duration: 4200,
          classNames: {
            toast: 'kan-toast',
            content: 'kan-toast__content',
            title: 'kan-toast__title',
            description: 'kan-toast__description',
            icon: 'kan-toast__icon',
          },
          style: {
            borderRadius: '12px',
            fontFamily: 'system-ui, "Segoe UI", Roboto, sans-serif',
            textAlign: 'left',
          },
        }}
      />
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
          <span
            aria-hidden="true"
            className="talk-button__dot"
            style={
              {
                '--voice-level': voiceLevel,
              } as CSSProperties
            }
          />
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
