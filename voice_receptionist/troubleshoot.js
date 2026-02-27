/**
 * troubleshoot.js — Guided AV/network troubleshooting decision trees
 *
 * Each "tree" is a small state machine. Nodes have a question;
 * each answer maps to either another node or a { resolution } terminal.
 *
 * Usage
 * ─────
 * const t = require('./troubleshoot');
 * const tree = t.startTree('audio');           // { treeId, nodeId, question }
 * const next = t.nextStep(tree.treeId, 'yes'); // { nodeId, question } or { resolution }
 */

'use strict';

// ─── Tree definitions ─────────────────────────────────────────────────────────

const TREES = {
  audio: {
    start: 'q1',
    nodes: {
      q1: {
        question: 'Is the amplifier or receiver powered on and showing a normal display?',
        yes: 'q2',
        no:  { resolution: 'Please power-cycle the amplifier: hold the power button for 5 seconds, wait 30 seconds, then power it back on. Does that restore audio?' },
      },
      q2: {
        question: 'Are you hearing no sound at all, or is the audio distorted / cutting out?',
        yes: 'q3',  // yes = no sound at all
        no:  'q4',  // no  = distorted
      },
      q3: {
        question: 'Is the correct input source selected on the amplifier (e.g. TV, Streaming, Vinyl)?',
        yes: { resolution: 'With the correct input selected and still no audio, the issue is likely a cable or zone-controller fault. I will schedule a technician visit.' },
        no:  { resolution: 'Please switch to the correct input. If the remote is unresponsive, try the physical buttons on the amplifier.' },
      },
      q4: {
        question: 'Does the distortion happen on all sources, or only one?',
        yes: { resolution: 'Distortion across all sources points to an amplifier or speaker-wiring issue. I will schedule a technician.' },
        no:  { resolution: 'Single-source distortion is usually a cable or streaming-app issue. Try a different cable or restart the affected source device.' },
      },
    },
  },

  video: {
    start: 'q1',
    nodes: {
      q1: {
        question: 'Is the display powered on and showing a picture, even if incorrect?',
        yes: 'q2',
        no:  { resolution: 'Check that the display is plugged in and the correct HDMI input is selected. If it still shows nothing, hold the power button on the display for 10 seconds to force-restart.' },
      },
      q2: {
        question: 'Is the issue a blank / black screen, or wrong content / wrong resolution?',
        yes: 'q3',  // yes = blank screen
        no:  { resolution: 'For wrong content, verify the source device is sending to the correct matrix or switch output. For resolution issues, change the output resolution on the source device to 1080p as a test.' },
      },
      q3: {
        question: 'Does the display show a "No Signal" message?',
        yes: { resolution: 'No Signal usually means the HDMI cable is loose or the source is off. Re-seat both ends of the HDMI cable and confirm the source device is powered on.' },
        no:  { resolution: 'A black screen without "No Signal" is often an HDCP handshake failure. Power off both the display and the source, wait 30 seconds, then power on the source first, followed by the display.' },
      },
    },
  },

  control4: {
    start: 'q1',
    nodes: {
      q1: {
        question: 'Is the Control4 controller (the small black box) showing a solid green LED?',
        yes: 'q2',
        no:  { resolution: 'A non-green LED means the controller lost power or crashed. Unplug the power adapter, wait 20 seconds, and plug it back in. Allow 2 minutes to fully reboot.' },
      },
      q2: {
        question: 'Are all Control4 touch-screens or the app unresponsive, or just one device?',
        yes: { resolution: 'If all devices are unresponsive the controller may have lost network connectivity. Check the network switch the controller is connected to. If the switch looks fine, a full controller reboot is the next step.' },
        no:  { resolution: 'A single unresponsive device is usually a Wi-Fi drop or the device needs a reboot. Force-quit and relaunch the Control4 app, or power-cycle the touch-screen.' },
      },
    },
  },

  lutron: {
    start: 'q1',
    nodes: {
      q1: {
        question: 'Are all Lutron dimmers unresponsive, or only certain rooms?',
        yes: { resolution: 'If all dimmers are down the Lutron hub (LEAP Bridge or RadioRA3 processor) has likely lost power. Locate the hub — usually a white or black box in the AV rack — and power-cycle it.' },
        no:  'q2',
      },
      q2: {
        question: 'Does the affected dimmer LED blink rapidly or show any unusual pattern?',
        yes: { resolution: 'Rapid blinking indicates a device fault or firmware issue. Hold the top and bottom buttons on the dimmer simultaneously for 6 seconds to factory-reset it. I can schedule a re-pairing visit if needed.' },
        no:  { resolution: 'A dim that is unresponsive but shows no LED activity may have lost its Lutron clear-connect association. Please press and release the top button 3 times rapidly — if no change, we will need a technician to re-pair the device.' },
      },
    },
  },

  networking: {
    start: 'q1',
    nodes: {
      q1: {
        question: 'Is the internet completely down for all devices in the home, or just some?',
        yes: 'q2',
        no:  { resolution: 'Partial outages are usually a Wi-Fi coverage or VLAN issue. Try moving the affected device closer to an access point, or connect it via Ethernet as a test.' },
      },
      q2: {
        question: 'Are the lights on your modem and router both showing solid (not blinking) status LEDs?',
        yes: { resolution: 'Lights look normal but internet is down — this often means the ISP has an outage. Check your ISP status page or call them. If the ISP is clear, a full power-cycle of the modem and router (in that order) is the next step.' },
        no:  { resolution: 'Unplug the modem first, wait 30 seconds, plug it back in and wait 60 seconds for it to sync. Then power-cycle the router. Full recovery can take 2–3 minutes.' },
      },
    },
  },

  cameras: {
    start: 'q1',
    nodes: {
      q1: {
        question: 'Are all cameras offline, or only specific ones?',
        yes: { resolution: 'All cameras offline usually means the NVR or PoE switch lost power. Check the rack and power-cycle the PoE switch. Allow 2 minutes for cameras to reconnect.' },
        no:  'q2',
      },
      q2: {
        question: 'Is the offline camera showing a solid amber or red LED on the unit itself?',
        yes: { resolution: 'A solid amber/red LED indicates the camera is powered but has lost network connectivity. Re-seat the Ethernet cable at the camera and at the switch port. If the issue persists the port or cable may need replacement.' },
        no:  { resolution: 'No LED at all means the camera has lost power. Check the PoE switch port status for that camera. If the port shows active, the camera itself may have failed and will need replacement.' },
      },
    },
  },
};

// ─── Session store (in-memory) ────────────────────────────────────────────────
// Maps treeId (uuid-ish string) → { treeName, currentNodeId }
const sessions = new Map();

let sessionCounter = 0;

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Start a new troubleshooting tree.
 * @param {string} category — one of: audio, video, control4, lutron, networking, cameras
 * @returns {{ treeId: string, nodeId: string, question: string }}
 */
function startTree(category) {
  const tree = TREES[category];
  if (!tree) throw new Error(`Unknown troubleshooting category: ${category}`);

  const treeId = `${category}-${++sessionCounter}-${Date.now()}`;
  sessions.set(treeId, { treeName: category, currentNodeId: tree.start });

  const node = tree.nodes[tree.start];
  return { treeId, nodeId: tree.start, question: node.question };
}

/**
 * Advance the tree with the caller's answer.
 * @param {string} treeId  — from startTree()
 * @param {string} answer  — 'yes' or 'no'
 * @returns {{ nodeId: string, question: string } | { resolution: string }}
 */
function nextStep(treeId, answer) {
  const session = sessions.get(treeId);
  if (!session) throw new Error(`Unknown treeId: ${treeId}`);

  const tree    = TREES[session.treeName];
  const curNode = tree.nodes[session.currentNodeId];
  const next    = curNode[answer.toLowerCase()];

  if (!next) throw new Error(`No '${answer}' branch from node ${session.currentNodeId}`);

  // Terminal node
  if (typeof next === 'object' && next.resolution) {
    sessions.delete(treeId);
    return { resolution: next.resolution };
  }

  // Advance to next node
  session.currentNodeId = next;
  const nextNode = tree.nodes[next];
  return { nodeId: next, question: nextNode.question };
}

module.exports = { startTree, nextStep };
