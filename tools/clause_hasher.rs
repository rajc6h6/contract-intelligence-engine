/// clause_hasher.rs — Deterministic SHA-256 content-addressable hasher
///
/// Generates a deterministic hex-encoded SHA-256 hash for contract clause text.
/// Used by seed_clauses.py to deduplicate clauses before inserting into pgvector:
/// each unique clause gets one embedding slot, preventing redundant API calls
/// and keeping the ivfflat index compact.
///
/// Why Rust?
/// ---------
/// SHA-256 is compute-bound. For large batch seeding (thousands of clauses),
/// Python's hashlib adds ~50µs overhead per call due to GIL contention and
/// object allocation. The compiled Rust binary removes that overhead entirely,
/// making it suitable as a high-throughput dedup filter in the seed pipeline.
///
/// Usage:
///   # From stdin (used by seed_clauses.py via subprocess):
///   echo "This Agreement shall not limit liability..." | ./clause_hasher
///
///   # From argument:
///   ./clause_hasher --text "This Agreement shall not limit liability..."
///
///   # From file:
///   ./clause_hasher --file contract_clause.txt
///
/// Build:
///   cd tools && cargo build --release
///   # Binary at: tools/target/release/clause_hasher
///
/// Integration with seed_clauses.py:
///   result = subprocess.run(["./tools/clause_hasher"], input=clause_text,
///                           capture_output=True, text=True)
///   content_hash = result.stdout.strip()

use clap::Parser;
use sha2::{Digest, Sha256};
use std::io::{self, Read};

#[derive(Parser, Debug)]
#[command(
    name = "clause_hasher",
    about = "Deterministic SHA-256 hasher for contract clause deduplication",
    long_about = "Reads clause text from stdin or --text/--file and outputs a hex SHA-256 hash.\n\
                  Used by the Contract Intelligence Engine seed pipeline to deduplicate\n\
                  clause embeddings before insertion into pgvector."
)]
struct Args {
    /// Clause text to hash (if omitted, reads from stdin)
    #[arg(short, long)]
    text: Option<String>,

    /// File containing clause text to hash
    #[arg(short, long)]
    file: Option<std::path::PathBuf>,

    /// Output only the hash (no trailing newline) — useful for subprocess pipes
    #[arg(long, default_value_t = false)]
    raw: bool,
}

fn hash_text(input: &str) -> String {
    let mut hasher = Sha256::new();
    // Normalise: trim whitespace, collapse multiple spaces for stability
    // This ensures two logically identical clauses with different formatting
    // produce the same hash (dedup robustness).
    let normalised: String = input
        .trim()
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ");
    hasher.update(normalised.as_bytes());
    format!("{:x}", hasher.finalize())
}

fn main() {
    let args = Args::parse();

    let input = if let Some(text) = args.text {
        text
    } else if let Some(file_path) = args.file {
        std::fs::read_to_string(&file_path).unwrap_or_else(|e| {
            eprintln!("Error reading file {:?}: {}", file_path, e);
            std::process::exit(1);
        })
    } else {
        // Read from stdin (default: subprocess pipe from seed_clauses.py)
        let mut buf = String::new();
        io::stdin()
            .read_to_string(&mut buf)
            .unwrap_or_else(|e| {
                eprintln!("Error reading stdin: {}", e);
                std::process::exit(1);
            });
        buf
    };

    if input.trim().is_empty() {
        eprintln!("Error: empty input — provide clause text via stdin, --text, or --file");
        std::process::exit(1);
    }

    let hash = hash_text(&input);

    if args.raw {
        print!("{}", hash);
    } else {
        println!("{}", hash);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_deterministic() {
        let text = "The total liability of either party shall not exceed $500,000";
        assert_eq!(hash_text(text), hash_text(text));
    }

    #[test]
    fn test_whitespace_normalisation() {
        let a = "  Liability   shall   not  exceed  ";
        let b = "Liability shall not exceed";
        assert_eq!(hash_text(a), hash_text(b));
    }

    #[test]
    fn test_different_clauses_different_hashes() {
        let a = "Liability shall not exceed $1M";
        let b = "Liability is uncapped and unlimited";
        assert_ne!(hash_text(a), hash_text(b));
    }

    #[test]
    fn test_output_length() {
        let hash = hash_text("test clause");
        assert_eq!(hash.len(), 64); // SHA-256 = 32 bytes = 64 hex chars
    }
}
