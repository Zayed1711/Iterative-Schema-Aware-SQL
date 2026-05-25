# Iterative Schema-Aware Self-Correction in SLMs

This repository contains the code, evaluation data, and execution logs for the paper: **"Iterative Schema-Aware Self-Correction in Small Language Models for Low-Resource Text-to-SQL Translation."**

## Overview
This project demonstrates how a 1.5B parameter Small Language Model (SLM) can achieve high Text-to-SQL execution accuracy (65.80%) on the Spider benchmark without relying on massive cloud APIs. It utilizes a deterministic SQLite compiler feedback loop, strictly capped at $k=3$ iterations to prevent infinite hallucination loops and maintain a low inference latency (~14 seconds).

## AI Declaration
During the preparation of this work the author(s) used Gemini AI, Claude and Perplexity in order to debug and improve the quality of the framework. After using the tool(s)/service(s), the author(s) reviewed and edited the code as needed and take(s) full responsibility for the content.

## Repository Contents
* `spider_rig.py`: The core Python pipeline (Context Injector, SQLite execution engine, and iterative feedback loop).
* `benchmark_system_flowchart.svg`: System architecture diagram.
* `spider_run_final_500.csv`: The aggregated benchmark results proving the 65.80% execution accuracy.
* `spider_run_full_1` through `4`: Raw execution logs for each iteration of the stratified Spider sample.

## Reproducibility 
To reproduce the findings in the paper, you can view the raw `.csv` data logs which track the query difficulty, outcome (`SUCCESS`, `FAILED_RETRY_LIMIT`, `UNANSWERABLE`), retry attempts, and exact total latency in seconds for every query evaluated.

## Author
* **B.M. Zayed Mahin**
* Department of Computer Science and Engineering, Daffodil International University
