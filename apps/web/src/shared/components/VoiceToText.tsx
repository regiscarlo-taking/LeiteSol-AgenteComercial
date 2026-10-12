import { useEffect, useRef, useState } from "react";

import "./VoiceToText.css";

interface SpeechAlternative {
  transcript: string;
}

interface SpeechResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechAlternative;
}

interface SpeechResultEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<SpeechResult>;
}

interface SpeechErrorEvent {
  readonly error: string;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

interface SpeechWindow extends Window {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
}

export interface VoiceToTextProps {
  onTranscript: (transcript: string) => void;
  language?: string;
  disabled?: boolean;
  className?: string;
}

const getRecognitionConstructor = (): (new () => SpeechRecognitionLike) | null => {
  const speechWindow = window as SpeechWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
};

const errorMessage = (error: string): string => {
  switch (error) {
    case "not-allowed":
    case "service-not-allowed":
      return "Permita o uso do microfone para ditar.";
    case "no-speech":
      return "Nenhuma fala foi detectada. Tente novamente.";
    case "audio-capture":
      return "Não foi possível acessar o microfone.";
    case "network":
      return "O reconhecimento de voz está indisponível pela rede.";
    default:
      return "Não foi possível iniciar o reconhecimento de voz.";
  }
};

export const VoiceToText = ({
  onTranscript,
  language = "pt-BR",
  disabled = false,
  className,
}: VoiceToTextProps) => {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const transcriptCallbackRef = useRef(onTranscript);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    transcriptCallbackRef.current = onTranscript;
  }, [onTranscript]);

  useEffect(
    () => () => {
      const recognition = recognitionRef.current;
      if (recognition) {
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.onend = null;
        recognition.abort();
      }
    },
    [],
  );

  useEffect(() => {
    if (disabled && listening) {
      recognitionRef.current?.stop();
    }
  }, [disabled, listening]);

  const startListening = () => {
    const Recognition = getRecognitionConstructor();
    if (!Recognition) {
      setError("Este navegador não oferece reconhecimento de voz. Você pode digitar a pergunta.");
      return;
    }

    try {
      recognitionRef.current?.abort();
      const recognition = new Recognition();
      recognition.lang = language;
      recognition.continuous = true;
      recognition.interimResults = false;
      recognition.onresult = (event) => {
        const finalTranscript = Array.from(
          { length: event.results.length - event.resultIndex },
          (_, index) => {
            const result = event.results[event.resultIndex + index];
            return result.isFinal ? result[0]?.transcript.trim() ?? "" : "";
          },
        )
          .filter(Boolean)
          .join(" ");
        if (finalTranscript) {
          transcriptCallbackRef.current(finalTranscript);
        }
      };
      recognition.onerror = (event) => {
        setError(errorMessage(event.error));
        setListening(false);
      };
      recognition.onend = () => setListening(false);
      recognitionRef.current = recognition;
      setError("");
      setListening(true);
      recognition.start();
    } catch {
      setListening(false);
      setError("Não foi possível iniciar o microfone. Verifique as permissões do navegador.");
    }
  };

  const stopListening = () => {
    recognitionRef.current?.stop();
    setListening(false);
  };

  return (
    <div className={`voice-to-text ${className ?? ""}`.trim()}>
      <button
        className={`voice-to-text__button${listening ? " is-listening" : ""}`}
        type="button"
        aria-label={listening ? "Parar ditado" : "Ditar mensagem"}
        aria-pressed={listening}
        disabled={disabled}
        onClick={listening ? stopListening : startListening}
      >
        <span aria-hidden="true">{listening ? "■" : "🎙"}</span>
        <span>{listening ? "Parar ditado" : "Ditar"}</span>
      </button>
      <span className="voice-to-text__status" role={error ? "alert" : "status"} aria-live="polite">
        {error || (listening ? "Ouvindo..." : "")}
      </span>
    </div>
  );
};
