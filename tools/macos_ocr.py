"""Read French text locally with Apple Vision, in the pixel space of the input."""
import re

import objc
import Vision
from Foundation import NSURL
from PIL import Image


def recognize(path):
    with Image.open(path) as image:
        width, height = image.size
    with objc.autorelease_pool():
        url = NSURL.fileURLWithPath_(str(path.resolve()))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(['fr-FR'])
        request.setUsesLanguageCorrection_(False)
        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError(f'Lecture OCR Apple Vision interrompue : {error}')
        lines, words = [], []
        complete_geometry = True
        for observation in request.results():
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            line = str(candidate.string())
            lines.append(line)
            for match in re.finditer(r'\S+', line):
                # NSRange counts UTF-16 code units. Vision's origin is bottom-left.
                start = len(line[:match.start()].encode('utf-16-le')) // 2
                length = len(match[0].encode('utf-16-le')) // 2
                region, _ = candidate.boundingBoxForRange_error_((start, length), None)
                if region is None:
                    complete_geometry = False
                    continue
                rect = region.boundingBox()
                words.append(dict(text=match[0], x=rect.origin.x*width,
                                  y=(1-rect.origin.y-rect.size.height)*height,
                                  width=rect.size.width*width, height=rect.size.height*height))
        return dict(lines=lines, text='\n'.join(lines), words=words if complete_geometry else [],
                    engine='Apple Vision fr-FR', confidence=None)
