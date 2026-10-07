# Third-party notice

`anthropic.txt` is OpenCode's system prompt for Claude models, copied from
`packages/opencode/src/session/prompt/anthropic.txt` in <https://github.com/anomalyco/opencode>
at release v1.18.35 (the upstream file is identical at v1.18.1 and on the dev branch).

The only change is one character: line 72 is an empty bullet written as `- ` upstream, and the trailing
space is removed here (`-`) because this repository's pre-commit hook strips trailing whitespace.

idea-oc installs it so that agents using a Bedrock inference profile get the same instructions as
agents using the Claude model directly. OpenCode chooses its instructions from the model id, and a
profile's id is an ARN that does not name the model.

OpenCode is distributed under the following licence.

MIT License

Copyright (c) 2025 opencode

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
