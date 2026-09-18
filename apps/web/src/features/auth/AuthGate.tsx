import { type FormEvent, type ReactNode, useState } from "react";

import { authenticate } from "../../shared/api";

interface AuthGateProps {
  children: ReactNode;
}

export const AuthGate = ({ children }: AuthGateProps) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [authenticated, setAuthenticated] = useState(
    Boolean(localStorage.getItem("leitesol_access_token")),
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const token = await authenticate(username, password);
      localStorage.setItem("leitesol_access_token", token.access_token);
      localStorage.setItem("leitesol_refresh_token", token.refresh_token);
      setAuthenticated(true);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (authenticated) {
    return <>{children}</>;
  }

  return (
    <main className="auth-shell">
      <form className="auth-panel" onSubmit={handleSubmit}>
        <p className="eyebrow">LeiteSol Agent Hub</p>
        <h1>Autenticar acesso</h1>
        <p className="auth-copy">Entre para consultar os dados comerciais do Fabric.</p>
        <label>
          Usuário
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Senha
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error ? <p className="auth-error">{error}</p> : null}
        <button className="primary-action" type="submit" disabled={busy}>
          {busy ? "Autenticando..." : "Autenticar"}
        </button>
      </form>
    </main>
  );
};