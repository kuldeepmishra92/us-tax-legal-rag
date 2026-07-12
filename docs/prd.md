# AI-Powered US Tax & Legal Research System

## Project Overview

### Goal

Build a high-precision AI-powered legal research system for the **US Tax & Legal domain**. The system should enable legal professionals to query a collection of approximately **100 legal documents** and receive accurate, summarized answers with precise legal citations and references.

---

# Milestone 1: Data Ingestion & Pre-processing

## Objective

Develop a robust document ingestion pipeline capable of processing multiple legal document types while preserving metadata required for accurate legal citations.

## Dataset

The system must process approximately **100 documents**, including:

* **Acts** – Statutory laws
* **Court Judgments** – Historical case law
* **POV (Point of View)** – Legal commentaries and expert analyses
* **Tax Documents** – IRS codes, tax regulations, and related documentation

## Requirements

Implement a document parser that:

* Extracts text accurately from each document.
* Preserves the **Page Index/Page Number** for every extracted section.
* Maintains document metadata required for future citation and verification.

> **Note:** Preserving page information is critical because it will later be used to generate exact legal references.

---

# Milestone 2: Search Architecture & Indexing

## Objective

Implement a **Hybrid Search Architecture** that retrieves highly relevant legal information with maximum precision.

## Search Requirements

### 1. Vector Search

* Semantic similarity search
* Context-aware retrieval using embeddings

### 2. Keyword Search

* Exact legal terminology matching
* Implemented using th e **ELK Stack (Elasticsearch)**

### 3. Hybrid Search

Combine:

* Vector Search
* Keyword Search

to maximize retrieval accuracy.

---

## Advanced Requirement: Graph RAG

Implement **Graph RAG** to model relationships across legal documents.

Examples include:

* Which Court Judgment cites a particular Act
* Which Tax Regulation references another legal document
* Cross-document legal relationships and dependencies

---

## Knowledge Standardization

Use **OKF (Open Knowledge Format)** to structure and organize the extracted legal knowledge before providing it to the LLM.

---

# Milestone 3: Feature Development (User Experience)

## Objective

Develop the user-facing features that legal professionals will use.

## Features

### 1. Natural Language Q&A

Allow users to ask legal questions in natural language.

Example:

> "What penalties apply under Section XYZ?"

The system should retrieve the most relevant legal context and generate an accurate response.

---

### 2. Legal Document Summarization

Generate concise and accurate summaries for:

* Court judgments
* Acts
* Legal commentaries
* Tax documents

---

### 3. Verification Features (Legal Must-Haves)

Every generated answer must include:

#### Citations

* Exact document name
* Relevant section (if available)

#### References

* Exact page number(s)
* Source document reference
* Direct verification path to the original material

The response must always be traceable back to its original legal source.

---

# Milestone 4: Quality Assurance & Evaluation

## Objective

Evaluate the reliability and accuracy of the system using a predefined **Golden Set**.

## Golden Set

A CSV or JSON dataset will be provided containing:

* **Sample Query** – The legal question
* **Ground Truth Answer** – The expected correct response
* **Source Document** – The document containing the correct answer

---

## Evaluation Tasks

Run the complete system against the Golden Set and evaluate:

### 1. Retrieval Accuracy

Measure whether the retrieval system successfully identifies the correct source document.

### 2. Faithfulness

Measure whether the LLM:

* Generates answers consistent with the retrieved context
* Avoids hallucinations
* Correctly summarizes the legal content

---

# Final Deliverables

## 1. Architecture Diagram

Create a system architecture illustrating the complete workflow:

```text
PDF Documents
      ↓
Document Parser
      ↓
Pre-processing & Chunking
      ↓
Vector Database + ELK (Keyword Index)
      ↓
Hybrid Retrieval
      ↓
(Optional) Graph RAG
      ↓
LLM
      ↓
Answer + Citations + References
```

---

## 2. Working Demo

Provide a functional application (UI or API) where users can:

* Submit legal queries
* Retrieve relevant legal information
* Receive summarized responses
* View citations and page references

---

## 3. Evaluation Report

Submit an evaluation report including:

* Retrieval Accuracy
* Faithfulness Score
* Overall performance on the Golden Set
* Observations, limitations, and potential improvements

---

# Expected Outcome

The completed system should:

* Process approximately 100 US legal and tax documents.
* Support Hybrid Search (Vector + ELK Keyword Search).
* Optionally enhance retrieval using Graph RAG.
* Preserve page-level metadata for precise citations.
* Answer legal questions with accurate summaries.
* Provide document names, page numbers, and references for verification.
* Demonstrate measurable performance using the provided Golden Set.
