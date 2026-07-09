#ifndef AXIOM_V2_ONNX_MQH
#define AXIOM_V2_ONNX_MQH

#include "AxiomV2Features.mqh"

class CAxiomV2Onnx
{
private:
   long m_handle;

public:
   CAxiomV2Onnx(void) : m_handle(INVALID_HANDLE) {}

   bool Initialize(const uchar &model_buffer[])
   {
      Release();
      m_handle = OnnxCreateFromBuffer(model_buffer, ONNX_LOGLEVEL_ERROR | ONNX_USE_CPU_ONLY);
      if(m_handle == INVALID_HANDLE)
         return false;
      const long input_shape[] = {1, AXIOM_V2_FEATURE_COUNT};
      const long output_shape[] = {1, 1};
      if(!OnnxSetInputShape(m_handle, 0, input_shape) || !OnnxSetOutputShape(m_handle, 0, output_shape))
      {
         Release();
         return false;
      }
      return true;
   }

   bool Score(const float &features[], float &score)
   {
      if(m_handle == INVALID_HANDLE || ArraySize(features) != AXIOM_V2_FEATURE_COUNT)
         return false;
      vectorf input_vector(AXIOM_V2_FEATURE_COUNT);
      vectorf output_vector(1);
      for(int index = 0; index < AXIOM_V2_FEATURE_COUNT; index++)
         input_vector[index] = features[index];
      if(!OnnxRun(m_handle, ONNX_NO_CONVERSION, input_vector, output_vector))
         return false;
      score = output_vector[0];
      return MathIsValidNumber((double)score);
   }

   void Release(void)
   {
      if(m_handle != INVALID_HANDLE)
      {
         OnnxRelease(m_handle);
         m_handle = INVALID_HANDLE;
      }
   }
};

#endif
