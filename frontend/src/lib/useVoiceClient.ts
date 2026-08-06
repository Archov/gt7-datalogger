// Mounts the Race Engineer voice client on a page that is allowed to speak.
// Only /dash and /engineer call this; every other page (notably the OBS
// overlay) still receives callouts on the WebSocket but never registers, so
// it can never become the active speaker.

import { useEffect } from "react";
import { subscribeWs, subscribeWsOpen } from "@/lib/wsBus";
import { clearVoiceQueue, useEngineer, type VoicePage } from "@/store/engineer";
import { useTelemetry } from "@/store/telemetry";

export function useVoiceClient(page: VoicePage): void {
  const setPage = useEngineer((s) => s.setPage);
  const wsConnected = useTelemetry((s) => s.wsConnected);

  useEffect(() => {
    setPage(page);
    const offMessage = subscribeWs((msg) => {
      const store = useEngineer.getState();
      if (msg.type === "voice_callout") store.handleCallout(msg.data);
      else if (msg.type === "voice_output_status") {
        store.setActiveClient(msg.data.active_client_id);
      } else if (msg.type === "race_engineer_status") store.applyServerStatus(msg.data);
    });
    const offOpen = subscribeWsOpen(() => {
      const store = useEngineer.getState();
      store.sendCapabilities();
      // Re-assert the claim after a reconnect, but only if this device was
      // already speaking in this page load — a stored preference alone must
      // not grab the microphone from another browser.
      if (store.enabled && store.audioReady && store.wantsSpeaker) store.claimSpeaker();
    });
    return () => {
      offMessage();
      offOpen();
      setPage(null);
    };
  }, [page, setPage]);

  useEffect(() => {
    // A dropped socket makes every pending message stale: whatever the server
    // wanted said is about a race state that has since moved on.
    if (!wsConnected) clearVoiceQueue();
  }, [wsConnected]);
}
