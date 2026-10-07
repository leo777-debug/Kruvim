"use client";

import { useRef, useState } from "react";
import { Play } from "lucide-react";

export default function DemoVideo() {
  const video = useRef<HTMLVideoElement>(null);
  const [started, setStarted] = useState(false);
  const [error, setError] = useState("");

  async function play() {
    setStarted(true);
    setError("");
    try {
      await video.current?.play();
      video.current?.focus();
    } catch {
      setError("Playback could not start. Please try the video controls.");
    }
  }

  return (
    <figure className="demo" id="demo" aria-labelledby="demo-title">
      <div className="demo-heading">
        <h2 id="demo-title">See Kruvim in action</h2>
        <span>Product walkthrough <span aria-hidden="true">/</span> 2:47</span>
      </div>
      <div className={`demo-player ${started ? "has-started" : ""}`}>
        <video
          ref={video}
          controls={started}
          controlsList="nodownload"
          playsInline
          preload="none"
          poster="/demo-poster.jpg"
          width={1280}
          height={800}
          tabIndex={started ? 0 : -1}
          aria-label="Kruvim product walkthrough: audience setup, simulation and results"
          aria-describedby="demo-description"
          onError={() => setError("The video could not load. Please refresh the page and try again.")}
        >
          <source src="/kruvim-demo.mp4" type="video/mp4" />
          Your browser does not support this video. Please try another browser.
        </video>
        {!started && <button className="demo-play" onClick={play} aria-label="Play the Kruvim demo video">
          <span className="play-symbol"><Play size={25} fill="currentColor" strokeWidth={1} /></span>
          <span>Watch the walkthrough</span>
        </button>}
      </div>
      <figcaption className="demo-caption">
        <span>Demo workspace · Recorded at 3× speed · No audio</span>
      </figcaption>
      <p className="demo-context">Follow a campaign from audience setup to simulated reactions and the final report.</p>
      {error && <p className="video-error" role="alert">{error}</p>}
      <details className="demo-description" id="demo-description">
        <summary>What the walkthrough shows</summary>
        <p>The recording follows a fitness campaign in a demo workspace: setting up the audience and simulation, exploring the knowledge graph and audience activity, then reviewing the results and analyst report. The run uses test data and the results screen is marked “Dry run”. This is a silent, accelerated product demonstration.</p>
      </details>
    </figure>
  );
}
