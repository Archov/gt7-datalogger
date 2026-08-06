// The dedicated Race Engineer page: /engineer (or #/engineer) renders a
// standalone voice surface with no dashboard chrome — for an OBS browser
// source, a phone propped on the desk, or troubleshooting voice output.
// The plain path is served by the backend (main.py) so URL validators that
// reject fragments still work.

export function isEngineerLocation(loc: { pathname: string; hash: string }): boolean {
  return (
    loc.pathname === "/engineer" ||
    loc.hash === "#/engineer" ||
    loc.hash.startsWith("#/engineer?")
  );
}
