import { useGSAP } from '@gsap/react'
import gsap from 'gsap'
import { Toaster, toast } from 'sonner'
import { useEffect, useRef, useState, type CSSProperties } from 'react'

gsap.registerPlugin(useGSAP)

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? `http://${window.location.hostname}:8000`
).replace(/\/$/, '')

type ApiEvent = {
  id: string
  title: string
  starts_at: string
  location?: string | null
  description?: string | null
  city?: string | null
  tags: string[]
  source: string
  url?: string | null
}

type MatchResponse = {
  transcript: string | null
  language: string | null
  events: ApiEvent[]
  pitch: string
  mode: 'match' | 'random'
}

const dateFormatter = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' })
const timeFormatter = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' })

function titleCase(value: string) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value
}

function isKyotoTechMeetup(event: ApiEvent) {
  return event.url?.toLowerCase().includes('meetup.com/kyoto-tech-meetup/events/') ?? false
}

function getResultsSummary(events: ApiEvent[]) {
  if (events.length === 0) return 'I am currently specialised in Kansai events, including Kyoto, Osaka, Kobe and Nara.'
  const names = events.slice(0, 2).map((event) => event.title).join(' and ')
  const suffix = events.length > 2 ? ` and ${events.length - 2} more` : ''
  return `We found ${events.length} event${events.length === 1 ? '' : 's'} for you: ${names}${suffix}.`
}

function App() {
  const [isDarkMode, setIsDarkMode] = useState(() => {
    const stored = window.localStorage.getItem('kan-scrape-theme')
    return stored ? stored === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
  })
  const [isListening, setIsListening] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [voiceLevel, setVoiceLevel] = useState(0)
  const [result, setResult] = useState<MatchResponse | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const microphoneStreamRef = useRef<MediaStream | null>(null)
  const meterFrameRef = useRef<number | null>(null)
  const appRef = useRef<HTMLElement | null>(null)
  const titleRef = useRef<HTMLHeadingElement | null>(null)
  const introRef = useRef<HTMLParagraphElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = isDarkMode ? 'dark' : 'light'
    window.localStorage.setItem('kan-scrape-theme', isDarkMode ? 'dark' : 'light')
  }, [isDarkMode])

  useGSAP(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const intro = gsap.timeline({ defaults: { ease: 'power3.out' } })
    intro.from(titleRef.current, { autoAlpha: 0, y: -32, duration: 1.35 })
    intro.from(introRef.current, { autoAlpha: 0, y: -18, duration: 1.1 }, '-=0.8')
    intro.from(buttonRef.current, {
      autoAlpha: 0,
      filter: 'blur(16px)',
      duration: 1.8,
      ease: 'power2.out',
      clearProps: 'filter',
    }, '-=0.55')
  }, { scope: appRef })

  const stopVoiceMeter = () => {
    if (meterFrameRef.current !== null) cancelAnimationFrame(meterFrameRef.current)
    meterFrameRef.current = null
    microphoneStreamRef.current?.getTracks().forEach((track) => track.stop())
    microphoneStreamRef.current = null
    if (audioContextRef.current) void audioContextRef.current.close()
    audioContextRef.current = null
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
      const rms = Math.sqrt(data.reduce((total, sample) => {
        const normalized = (sample - 128) / 128
        return total + normalized * normalized
      }, 0) / data.length)
      setVoiceLevel(rms > 0.045 ? Math.min((rms - 0.045) * 5, 1) : 0)
      meterFrameRef.current = requestAnimationFrame(measure)
    }
    measure()
    return stream
  }

  const startListening = async () => {
    if (isListening || isSearching) return
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      toast.error('Audio recording unavailable', { description: 'Use a modern browser with microphone support.' })
      return
    }
    try {
      const stream = await startVoiceMeter()
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm'
      const recorder = new MediaRecorder(stream, { mimeType })
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorderRef.current = recorder
      recorder.start()
      setResult(null)
      setIsListening(true)
    } catch {
      stopVoiceMeter()
      toast.error('Microphone access is needed', { description: 'Allow microphone access to search for events.' })
    }
  }

  const searchWithAudio = async (audio: Blob) => {
    if (audio.size === 0) {
      setIsSearching(false)
      toast.info('Nothing to search yet', { description: 'Speak into the microphone before stopping the search.' })
      return
    }
    const formData = new FormData()
    formData.append('audio', audio, 'voice.webm')
    try {
      const response = await fetch(`${API_BASE_URL}/api/match/voice`, { method: 'POST', body: formData })
      if (!response.ok) throw new Error(`Search failed with ${response.status}`)
      const nextResult = await response.json() as MatchResponse
      setResult(nextResult)
      toast.success(nextResult.mode === 'match' ? 'Events found for you' : 'Here is a surprise pick', {
        description: getResultsSummary(nextResult.events),
      })
    } catch (error) {
      const backendUnavailable = error instanceof TypeError
      toast.error(backendUnavailable ? 'Backend unavailable' : 'Search failed', {
        description: backendUnavailable
          ? `Could not reach ${API_BASE_URL}. Start the backend with pnpm dev and try again.`
          : 'The meetup search could not be completed. Try again.',
      })
    } finally {
      setIsSearching(false)
    }
  }

  const stopListening = () => {
    const recorder = recorderRef.current
    if (!recorder) return
    setIsListening(false)
    setIsSearching(true)
    recorder.onstop = () => {
      const audio = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      recorderRef.current = null
      stopVoiceMeter()
      void searchWithAudio(audio)
    }
    recorder.stop()
  }

  return (
    <main ref={appRef} className="app-shell">
      <button
        className="theme-toggle"
        type="button"
        aria-label={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
        aria-pressed={isDarkMode}
        onClick={() => setIsDarkMode((current) => !current)}
      >
        <span aria-hidden="true">{isDarkMode ? '☀' : '◐'}</span>
        <span>{isDarkMode ? 'Light mode' : 'Dark mode'}</span>
      </button>
      <Toaster
        position="top-right"
        theme={isDarkMode ? 'dark' : 'light'}
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
        }}
      />
      <h1 ref={titleRef}>Kyoto Meetup Finder</h1>
      <p ref={introRef} className="intro">Speak into the microphone in any language to find the best meetup events.</p>
      <button
        ref={buttonRef}
        className={`talk-button${isListening ? ' is-listening' : ''}${isSearching ? ' is-searching' : ''}`}
        type="button"
        aria-pressed={isListening}
        aria-busy={isSearching}
        aria-label={isSearching ? 'Searching for meetups' : isListening ? 'Stop listening and search' : 'Start listening'}
        disabled={isSearching}
        onClick={isListening ? stopListening : () => void startListening()}
      >
        {isSearching ? <span aria-hidden="true" className="talk-button__loader" /> : (
          <span aria-hidden="true" className="talk-button__dot" style={{ '--voice-level': voiceLevel } as CSSProperties} />
        )}
        {isSearching ? 'Searching…' : isListening ? 'Stop and search' : 'Start speaking'}
      </button>

      {result && (
        <section className="results-panel" aria-live="polite">
          <p className="results-pitch">{getResultsSummary(result.events)}</p>
          <div className="results-heading"><span>Curated for Kyoto</span><span>{result.events.length} events</span></div>
          <div className="event-list">
            {result.events.map((event) => (
              <article className={`event-card${isKyotoTechMeetup(event) ? ' event-card--featured' : ''}`} key={event.id}>
                <div className="event-card__date">{dateFormatter.format(new Date(event.starts_at))}</div>
                <div className="event-card__content">
                  <div className="event-card__labels">
                    <p className="event-card__category">{titleCase(event.tags[0] ?? event.source)}</p>
                    {isKyotoTechMeetup(event) && <span className="event-card__featured-badge" aria-label="Kyoto Tech Meetup" title="Kyoto Tech Meetup">★</span>}
                  </div>
                  <h2>{event.title}</h2>
                  <p className="event-card__meta">{event.location ?? event.city ?? 'Kansai'} · {timeFormatter.format(new Date(event.starts_at))}</p>
                  <p className="event-card__description">{event.description ?? 'Details will be available from the event organiser.'}</p>
                  {event.url && <a className="event-card__link" href={event.url} target="_blank" rel="noreferrer">View event</a>}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      <footer className="app-footer">
        Made with <span aria-label="love">♥</span> by and for the Kyoto Tech Meetup community.
      </footer>
    </main>
  )
}

export default App
