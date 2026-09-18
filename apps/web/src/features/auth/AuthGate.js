import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { authenticate } from "../../shared/api";
export const AuthGate = ({ children }) => {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [authenticated, setAuthenticated] = useState(Boolean(localStorage.getItem("leitesol_access_token")));
    const handleSubmit = async (event) => {
        event.preventDefault();
        setBusy(true);
        setError("");
        try {
            const token = await authenticate(username, password);
            localStorage.setItem("leitesol_access_token", token.access_token);
            localStorage.setItem("leitesol_refresh_token", token.refresh_token);
            setAuthenticated(true);
        }
        catch (requestError) {
            setError(requestError.message);
        }
        finally {
            setBusy(false);
        }
    };
    if (authenticated) {
        return _jsx(_Fragment, { children: children });
    }
    return (_jsx("main", { className: "auth-shell", children: _jsxs("form", { className: "auth-panel", onSubmit: handleSubmit, children: [_jsx("p", { className: "eyebrow", children: "LeiteSol Agent Hub" }), _jsx("h1", { children: "Autenticar acesso" }), _jsx("p", { className: "auth-copy", children: "Entre para consultar os dados comerciais do Fabric." }), _jsxs("label", { children: ["Usu\u00E1rio", _jsx("input", { value: username, onChange: (event) => setUsername(event.target.value), autoComplete: "username", required: true })] }), _jsxs("label", { children: ["Senha", _jsx("input", { type: "password", value: password, onChange: (event) => setPassword(event.target.value), autoComplete: "current-password", required: true })] }), error ? _jsx("p", { className: "auth-error", children: error }) : null, _jsx("button", { className: "primary-action", type: "submit", disabled: busy, children: busy ? "Autenticando..." : "Autenticar" })] }) }));
};
