import os
import shutil
import tempfile
from time import perf_counter

from doctr import models as models
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
from PIL import Image

from inference.core.data_models import (
    DoctrOCRInferenceRequest,
    DoctrOCRInferenceResponse,
)
from inference.core.env import MODEL_CACHE_DIR
from inference.core.models.roboflow import RoboflowCoreModel
from inference.core.utils.image_utils import load_image


class DocTR(RoboflowCoreModel):
    def __init__(self, *args, **kwargs):
        """Initializes the DocTR model.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        model_id = model_id.lower()

        os.environ["DOCTR_CACHE_DIR"] = os.path.join(MODEL_CACHE_DIR, "doctr_rec")

        det_model = DocTRDet(api_key=kwargs.get("api_key"))
        rec_model = DocTRRec(api_key=kwargs.get("api_key"))

        os.makedirs("/tmp/cache/doctr_rec/models/", exist_ok=True)
        os.makedirs("/tmp/cache/doctr_det/models/", exist_ok=True)

        shutil.copyfile(
            "/tmp/cache/doctr_det/db_resnet50/model.pt",
            "/tmp/cache/doctr_det/models/db_resnet50-ac60cadc.pt",
        )
        shutil.copyfile(
            "/tmp/cache/doctr_rec/crnn_vgg16_bn/model.pt",
            "/tmp/cache/doctr_rec/models/crnn_vgg16_bn-9762b0b0.pt",
        )

        self.model = ocr_predictor(
            det_arch=det_model.version_id,
            reco_arch=rec_model.version_id,
            pretrained=True,
        )

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        DocTR pre-processes images as part of its inference pipeline.

        Thus, no preprocessing is required here.
        """
        pass

    def infer(self, request: DoctrOCRInferenceRequest):
        """
        Run inference on a provided image.

        Args:
            request (DoctrOCRInferenceRequest): The inference request.

        Returns:
            DoctrOCRInferenceResponse: The inference response.
        """
        t1 = perf_counter()

        img = load_image(request["image"]["value"])

        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            img.save(f.name)

            doc = DocumentFile.from_images([f.name])

            result = self.model(doc).export()

            t2 = perf_counter() - t1

            result = result["pages"][0]["blocks"]

            result = [
                " ".join([word["value"] for word in line["words"]])
                for block in result
                for line in block["lines"]
            ]

            result = " ".join(result)

            return DoctrOCRInferenceResponse(
                result=result,
                time=t2,
            )

    def get_infer_bucket_file_list(self) -> list:
        """Get the list of required files for inference.

        Returns:
            list: A list of required files for inference, e.g., ["model.pt"].
        """
        return ["model.pt"]


class DocTRRec(RoboflowCoreModel):
    def __init__(self, *args, model_id: str = "doctr_rec/crnn_vgg16_bn", **kwargs):
        """Initializes the DocTR model.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        pass

        self.get_infer_bucket_file_list()

        super().__init__(*args, model_id=model_id, **kwargs)

    def get_infer_bucket_file_list(self) -> list:
        """Get the list of required files for inference.

        Returns:
            list: A list of required files for inference, e.g., ["model.pt"].
        """
        return ["model.pt"]


class DocTRDet(RoboflowCoreModel):
    """DocTR class for document Optical Character Recognition (OCR).

    Attributes:
        doctr: The DocTR model.
        ort_session: ONNX runtime inference session.
    """

    def __init__(self, *args, model_id: str = "doctr_det/db_resnet50", **kwargs):
        """Initializes the DocTR model.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """

        self.get_infer_bucket_file_list()

        super().__init__(*args, model_id=model_id, **kwargs)

    def get_infer_bucket_file_list(self) -> list:
        """Get the list of required files for inference.

        Returns:
            list: A list of required files for inference, e.g., ["model.pt"].
        """
        return ["model.pt"]
