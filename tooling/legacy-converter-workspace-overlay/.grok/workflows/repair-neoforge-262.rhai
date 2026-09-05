let meta = #{
    name: "repair-neoforge-262",
    description: "Repair a failed NeoForge 26.2 converter output using evidence packet + sequential agents",
    when_to_use: "Fix-in-Grok failed output folders; compile-errors.log repair toward destination-Java build",
    phases: [
        #{ title: "Packet", detail: "Confirm failed-output evidence" },
        #{ title: "Research", detail: "One 262r/primer shard excerpts" },
        #{ title: "Implement", detail: "mc-code from packet" },
        #{ title: "Review", detail: "mc-reviewer vs packet" },
    ],
};

let research_schema = #{
    "type": "object",
    "required": ["shard_id", "next_agent", "summary"],
    "properties": #{
        "shard_id": #{ "type": "string" },
        "primer_shard": #{ "type": "string" },
        "next_agent": #{ "type": "string" },
        "summary": #{ "type": "string" },
        "excerpts": #{ "type": "array", "maxItems": 4, "items": #{ "type": "string" } },
    },
};

let implement_schema = #{
    "type": "object",
    "required": ["files_changed", "confidence", "blocked"],
    "properties": #{
        "files_changed": #{ "type": "array", "items": #{ "type": "string" } },
        "confidence": #{ "type": "number" },
        "blocked": #{ "type": "boolean" },
        "notes": #{ "type": "string" },
    },
};

let review_schema = #{
    "type": "object",
    "required": ["recommendation", "findings"],
    "properties": #{
        "recommendation": #{ "type": "string" },
        "findings": #{ "type": "array", "maxItems": 8, "items": #{
            "type": "object",
            "required": ["issue"],
            "properties": #{
                "file": #{ "type": "string" },
                "issue": #{ "type": "string" },
            },
        }},
    },
};

let failed = if args == () { () } else { args.failed_output };
if failed == () {
    pause("verification", "Pass args.failed_output — absolute path to the failed converter output folder.");
}

phase("Packet");
let packet_prompt = "";
packet_prompt += "FAILED OUTPUT: " + failed + ". ";
packet_prompt += "Read GROK_REPAIR_PROMPT.md, MIGRATION_EVIDENCE.md, SOURCE_PROFILE.json, compile-errors.log. ";
packet_prompt += "Create or update EVIDENCE_PACKET.md using the template at ";
packet_prompt += ".grok/skills/repair-failed-262-output/references/evidence-packet-template.md. ";
packet_prompt += "Keep under 9000 characters. Return the absolute packet path and detected source_version.";
let packet_agent = agent(packet_prompt, #{
    label: "packet",
    agent_type: "mc-fast",
    capability_mode: "read-write",
});
if packet_agent == () || !packet_agent.success {
    complete(#{ summary: "Failed to create evidence packet", failed_output: failed });
}

phase("Research");
let research_prompt = "";
research_prompt += "FAILED OUTPUT: " + failed + ". ";
research_prompt += "Read EVIDENCE_PACKET.md in that folder. Open ONE matching 262r shard under C:\\gokuai\\Data\\262r. ";
research_prompt += "Optionally one primer_changes shard. Return shard_id, primer_shard, up to 4 short excerpts, next_agent (mc-fast or mc-code), summary. ";
research_prompt += "Do not edit Java sources. Do not dump full primers.";
let research = agent(research_prompt, #{
    label: "research",
    agent_type: "mc-research",
    capability_mode: "read-only",
    output_schema: research_schema,
});
if research == () || !research.success {
    complete(#{ summary: "Research agent failed", failed_output: failed });
}

let next_impl = "mc-code";
if research.output != () && research.output.next_agent != () && research.output.next_agent != "" {
    next_impl = research.output.next_agent;
}
if next_impl != "mc-fast" && next_impl != "mc-code" {
    next_impl = "mc-code";
}

phase("Implement");
let impl_prompt = "";
impl_prompt += "FAILED OUTPUT: " + failed + ". ";
impl_prompt += "Work ONLY from EVIDENCE_PACKET.md and the research summary. ";
impl_prompt += "Research summary: " + json_encode(research.output) + ". ";
impl_prompt += "Apply the minimal fix for this error family. Do not rediscover the corpus. ";
impl_prompt += "Do not run Gradle unless necessary; parent validates with destination Java.";
let impl = agent(impl_prompt, #{
    label: "implement",
    agent_type: next_impl,
    capability_mode: "all",
    output_schema: implement_schema,
});
if impl == () || !impl.success {
    complete(#{ summary: "Implement agent failed", failed_output: failed, research: research.output });
}
if impl.output != () && impl.output.blocked == true {
    complete(#{
        summary: "Implement blocked — need more evidence",
        failed_output: failed,
        research: research.output,
        implement: impl.output,
    });
}

phase("Review");
let review_prompt = "";
review_prompt += "FAILED OUTPUT: " + failed + ". ";
review_prompt += "Review changes against EVIDENCE_PACKET.md and implement notes. ";
review_prompt += "Implement result: " + json_encode(impl.output) + ". ";
review_prompt += "Read-only. recommendation must be ship, fix, or encode. Max 8 findings.";
let review = agent(review_prompt, #{
    label: "review",
    agent_type: "mc-reviewer",
    capability_mode: "read-only",
    output_schema: review_schema,
});

let rec = "fix";
if review != () && review.success && review.output != () && review.output.recommendation != () {
    rec = review.output.recommendation;
}

log("Parent must run Build-WithDestinationJava.ps1 on " + failed + " before treating as green.");
complete(#{
    summary: "Repair loop finished — validate with destination Java next",
    failed_output: failed,
    research: research.output,
    implement: impl.output,
    review: if review != () && review.success { review.output } else { () },
    recommendation: rec,
    validate_command: "powershell -NoProfile -File C:\\gokuai\\projects\\RB-Legacy-Java-Converter\\tools\\Build-WithDestinationJava.ps1 -ProjectRoot \"" + failed + "\"",
});
