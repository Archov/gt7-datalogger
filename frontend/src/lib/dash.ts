// Driver dashboard route: /dash (or #/dash) renders full-screen without the
// app chrome. ?layout=<name-or-id> loads a server layout, ?preset=<key> one of
// the built-ins, ?demo=1 forces placeholder data.

export interface DashParams {
  layout: string | null;
  preset: string | null;
  demo: boolean;
}

export function isDashLocation(loc: { pathname: string; hash: string }): boolean {
  return (
    loc.pathname === "/dash" ||
    loc.hash === "#/dash" ||
    loc.hash.startsWith("#/dash?")
  );
}

export function parseDashParams(loc: { search: string; hash: string }): DashParams {
  const query = loc.hash.includes("?")
    ? loc.hash.slice(loc.hash.indexOf("?") + 1)
    : loc.search.replace(/^\?/, "");
  const params = new URLSearchParams(query);
  const demo = params.get("demo");
  return {
    layout: params.get("layout"),
    preset: params.get("preset"),
    demo: demo === "1" || demo === "true",
  };
}
