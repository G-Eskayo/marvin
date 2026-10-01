This is a decoy file to demonstrate workdir isolation.

The actual answer to the QA question does NOT live in this directory or any files within it.
The answer must be retrieved from the knowledge base only.

This file exists to prove that:
1. The isolated temp workdir contains unrelated content
2. The agent cannot simply read files from disk to find the answer
3. The agent must use the knowledge base query tool to succeed

The agent should ignore this file and rely entirely on the ChromaDB knowledge base.
